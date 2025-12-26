"""User management routes (admin only)."""

import logging
from typing import Any

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from ...config import get_settings
from ..auth import get_cognito_client
from ..deps import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


# === Schemas ===


class UserInvite(BaseModel):
    """Request per invitare un nuovo utente."""

    email: EmailStr


class UserResponse(BaseModel):
    """Risposta con dati utente Cognito."""

    username: str
    email: str | None
    status: str  # CONFIRMED, FORCE_CHANGE_PASSWORD, etc.
    created_at: str
    enabled: bool


class UserDeleteResponse(BaseModel):
    """Risposta eliminazione utente."""

    status: str
    message: str


# === API Endpoints ===


@router.get("", response_model=list[UserResponse])
async def list_users(admin: dict[str, Any] = Depends(require_admin)) -> list[UserResponse]:
    """Lista tutti gli utenti del pool Cognito."""
    settings = get_settings()
    client = get_cognito_client()

    try:
        users = []
        paginator = client.get_paginator("list_users")

        for page in paginator.paginate(
            UserPoolId=settings.auth.cognito_user_pool_id,
            PaginationConfig={"MaxItems": 100},
        ):
            for user in page.get("Users", []):
                attrs = {a["Name"]: a["Value"] for a in user.get("Attributes", [])}
                users.append(
                    UserResponse(
                        username=user["Username"],
                        email=attrs.get("email"),
                        status=user["UserStatus"],
                        created_at=user["UserCreateDate"].isoformat(),
                        enabled=user["Enabled"],
                    )
                )

        return users

    except ClientError as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Errore nel recupero utenti")


@router.post("", response_model=UserResponse)
async def invite_user(
    data: UserInvite,
    admin: dict[str, Any] = Depends(require_admin),
) -> UserResponse:
    """
    Invita un nuovo utente.
    Cognito inviera automaticamente email con credenziali temporanee.
    """
    settings = get_settings()
    client = get_cognito_client()

    try:
        response = client.admin_create_user(
            UserPoolId=settings.auth.cognito_user_pool_id,
            Username=data.email,
            UserAttributes=[
                {"Name": "email", "Value": data.email},
                {"Name": "email_verified", "Value": "true"},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )

        user = response["User"]
        attrs = {a["Name"]: a["Value"] for a in user.get("Attributes", [])}

        logger.info(f"User {data.email} invited by admin {admin.get('email')}")

        return UserResponse(
            username=user["Username"],
            email=attrs.get("email"),
            status=user["UserStatus"],
            created_at=user["UserCreateDate"].isoformat(),
            enabled=user["Enabled"],
        )

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        error_msg = e.response.get("Error", {}).get("Message", "")

        if error_code == "UsernameExistsException":
            raise HTTPException(status_code=409, detail="Utente gia esistente")
        if error_code == "InvalidParameterException":
            raise HTTPException(status_code=400, detail=f"Parametro non valido: {error_msg}")
        logger.error(f"Error creating user: {error_code} - {error_msg}")
        raise HTTPException(status_code=500, detail="Errore nella creazione utente")


@router.delete("/{username}", response_model=UserDeleteResponse)
async def delete_user(
    username: str,
    admin: dict[str, Any] = Depends(require_admin),
) -> UserDeleteResponse:
    """Elimina un utente dal pool Cognito."""
    settings = get_settings()
    client = get_cognito_client()

    # Impedisci auto-eliminazione
    admin_email = admin.get("email", "")
    admin_username = admin.get("username", "")
    if username in (admin_email, admin_username):
        raise HTTPException(status_code=400, detail="Non puoi eliminare te stesso")

    try:
        client.admin_delete_user(
            UserPoolId=settings.auth.cognito_user_pool_id,
            Username=username,
        )

        logger.info(f"User {username} deleted by admin {admin.get('email')}")

        return UserDeleteResponse(
            status="ok",
            message=f"Utente {username} eliminato",
        )

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")

        if error_code == "UserNotFoundException":
            raise HTTPException(status_code=404, detail="Utente non trovato")
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(status_code=500, detail="Errore nell'eliminazione utente")
