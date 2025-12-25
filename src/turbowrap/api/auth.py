"""Authentication module for AWS Cognito integration."""

import logging
import time
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError
from jose import JWTError, jwt

from ..config import get_settings

logger = logging.getLogger(__name__)

# Cache for Cognito JWKS (JSON Web Key Set)
_jwks_cache: dict[str, Any] = {}
_jwks_cache_time: float = 0
JWKS_CACHE_TTL = 3600  # 1 hour


def get_cognito_client():
    """Get boto3 Cognito Identity Provider client."""
    settings = get_settings()
    return boto3.client(
        "cognito-idp",
        region_name=settings.auth.cognito_region,
    )


def get_jwks() -> dict[str, Any]:
    """Get Cognito JWKS (cached)."""
    global _jwks_cache, _jwks_cache_time

    settings = get_settings()
    now = time.time()

    if _jwks_cache and (now - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    # Fetch JWKS from Cognito
    region = settings.auth.cognito_region
    pool_id = settings.auth.cognito_user_pool_id
    jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"

    try:
        response = httpx.get(jwks_url, timeout=10)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_time = now
        return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        if _jwks_cache:
            return _jwks_cache
        raise


def cognito_login(email: str, password: str) -> dict[str, str] | None:
    """
    Authenticate user with Cognito using email/password.

    Args:
        email: User email
        password: User password

    Returns:
        Dict with tokens (access_token, id_token, refresh_token) or None if failed
    """
    settings = get_settings()
    client = get_cognito_client()

    try:
        response = client.initiate_auth(
            ClientId=settings.auth.cognito_app_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password,
            },
        )

        result = response.get("AuthenticationResult", {})
        return {
            "access_token": result.get("AccessToken"),
            "id_token": result.get("IdToken"),
            "refresh_token": result.get("RefreshToken"),
            "expires_in": result.get("ExpiresIn", 3600),
        }

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        error_msg = e.response.get("Error", {}).get("Message", "")

        if error_code in ("NotAuthorizedException", "UserNotFoundException"):
            logger.warning(f"Login failed for {email}: {error_code}")
            return None
        if error_code == "UserNotConfirmedException":
            logger.warning(f"User {email} not confirmed")
            return None
        if error_code == "PasswordResetRequiredException":
            logger.warning(f"Password reset required for {email}")
            return None
        logger.error(f"Cognito error: {error_code} - {error_msg}")
        raise


def verify_token(token: str) -> dict[str, Any] | None:
    """
    Verify Cognito JWT token.

    Args:
        token: JWT access token or ID token

    Returns:
        Decoded token claims or None if invalid
    """
    settings = get_settings()

    try:
        # Get JWKS
        jwks = get_jwks()

        # Get token header to find key ID
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Find matching key
        rsa_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

        if not rsa_key:
            logger.warning("No matching key found for token")
            return None

        # Verify token
        return jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.auth.cognito_app_client_id,
            issuer=f"https://cognito-idp.{settings.auth.cognito_region}.amazonaws.com/{settings.auth.cognito_user_pool_id}",
        )


    except JWTError as e:
        logger.warning(f"Token verification failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        return None


def refresh_access_token(refresh_token: str) -> dict[str, str] | None:
    """
    Refresh access token using refresh token.

    Args:
        refresh_token: Cognito refresh token

    Returns:
        New tokens or None if failed
    """
    settings = get_settings()
    client = get_cognito_client()

    try:
        response = client.initiate_auth(
            ClientId=settings.auth.cognito_app_client_id,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={
                "REFRESH_TOKEN": refresh_token,
            },
        )

        result = response.get("AuthenticationResult", {})
        return {
            "access_token": result.get("AccessToken"),
            "id_token": result.get("IdToken"),
            "expires_in": result.get("ExpiresIn", 3600),
        }

    except ClientError as e:
        logger.warning(f"Token refresh failed: {e}")
        return None


def get_user_info(access_token: str) -> dict[str, Any] | None:
    """
    Get user info from Cognito using access token.

    Args:
        access_token: Valid Cognito access token

    Returns:
        User attributes dict or None
    """
    client = get_cognito_client()

    try:
        response = client.get_user(AccessToken=access_token)

        # Convert attributes list to dict
        attrs = {}
        for attr in response.get("UserAttributes", []):
            attrs[attr["Name"]] = attr["Value"]

        return {
            "username": response.get("Username"),
            "email": attrs.get("email"),
            "email_verified": attrs.get("email_verified") == "true",
            "sub": attrs.get("sub"),
            "attributes": attrs,
        }

    except ClientError as e:
        logger.warning(f"Failed to get user info: {e}")
        return None
