"""
AWS Secrets Manager utility for fetching API keys.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# AWS Configuration
AWS_REGION = "eu-west-3"
SECRET_NAME = "agent-zero/global/api-keys"

# Cache for secrets
_secrets_cache: dict[str, Any] | None = None


def get_secrets() -> dict[str, Any]:
    """
    Fetch secrets from AWS Secrets Manager.

    Returns:
        dict with API keys (ANTHROPIC_API_KEY, GEMINI_API_KEY, etc.)
    """
    global _secrets_cache

    if _secrets_cache is not None:
        return _secrets_cache

    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError

        client = boto3.client("secretsmanager", region_name=AWS_REGION)

        response = client.get_secret_value(SecretId=SECRET_NAME)
        secrets: dict[str, Any] = json.loads(response["SecretString"])

        _secrets_cache = secrets
        logger.info(f"Successfully fetched secrets from AWS ({SECRET_NAME})")
        return secrets

    except NoCredentialsError:
        logger.warning("AWS credentials not found - running locally without AWS")
        return {}
    except ClientError as e:
        logger.error(f"Failed to fetch secrets from AWS: {e}")
        return {}
    except ImportError:
        logger.warning("boto3 not installed - cannot fetch AWS secrets")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error fetching secrets: {e}")
        return {}


def get_anthropic_api_key() -> str | None:
    """Get ANTHROPIC_API_KEY from AWS Secrets Manager."""
    secrets = get_secrets()
    return secrets.get("ANTHROPIC_API_KEY")


def get_gemini_api_key() -> str | None:
    """Get GEMINI_API_KEY from AWS Secrets Manager."""
    secrets = get_secrets()
    return secrets.get("GEMINI_API_KEY")


def get_google_api_key() -> str | None:
    """Get GOOGLE_API_KEY from AWS Secrets Manager."""
    secrets = get_secrets()
    return secrets.get("GOOGLE_API_KEY")
