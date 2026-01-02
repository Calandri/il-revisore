"""User management routes (admin only)."""

import logging
from typing import Any

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db.models import Repository, User, UserRepository, UserRole
from ..auth import get_cognito_client
from ..deps import get_db, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


# === Schemas ===


class UserInvite(BaseModel):
    """Request per invitare un nuovo utente."""

    email: EmailStr
    role: str = Field(default="coder", description="Ruolo iniziale: admin, coder, mockupper")


class UserResponse(BaseModel):
    """Risposta con dati utente Cognito + ruolo locale."""

    username: str
    email: str | None
    status: str  # CONFIRMED, FORCE_CHANGE_PASSWORD, etc.
    created_at: str
    enabled: bool
    # RBAC fields from local DB
    user_id: str | None = None  # Local DB ID
    role: str | None = None  # admin, coder, mockupper
    repository_ids: list[str] = Field(default_factory=list)  # Assigned repos


class UserDeleteResponse(BaseModel):
    """Risposta eliminazione utente."""

    status: str
    message: str


class UserRoleUpdate(BaseModel):
    """Request per aggiornare il ruolo di un utente."""

    role: str = Field(..., description="Nuovo ruolo: admin, coder, mockupper")


class UserRepoAssign(BaseModel):
    """Request per assegnare repository a un utente."""

    repository_ids: list[str] = Field(..., description="Lista di repository UUID")


# === API Endpoints ===


@router.get("", response_model=list[UserResponse])
async def list_users(
    admin: dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    """Lista tutti gli utenti del pool Cognito con dati RBAC locali."""
    settings = get_settings()
    client = get_cognito_client()

    # Load all local users for enrichment
    local_users = {u.cognito_sub: u for u in db.query(User).all()}

    # Load all user-repo assignments
    user_repos: dict[str, list[str]] = {}
    for ur in db.query(UserRepository).all():
        if ur.user_id not in user_repos:
            user_repos[ur.user_id] = []
        user_repos[ur.user_id].append(ur.repository_id)

    try:
        users = []
        paginator = client.get_paginator("list_users")

        for page in paginator.paginate(
            UserPoolId=settings.auth.cognito_user_pool_id,
            PaginationConfig={"MaxItems": 100},
        ):
            for user in page.get("Users", []):
                attrs = {a["Name"]: a["Value"] for a in user.get("Attributes", [])}
                cognito_sub = attrs.get("sub")

                # Get local user data
                local_user = local_users.get(cognito_sub) if cognito_sub else None

                users.append(
                    UserResponse(
                        username=user["Username"],
                        email=attrs.get("email"),
                        status=user["UserStatus"],
                        created_at=user["UserCreateDate"].isoformat(),
                        enabled=user["Enabled"],
                        # RBAC fields
                        user_id=local_user.id if local_user else None,
                        role=local_user.role if local_user else None,
                        repository_ids=user_repos.get(local_user.id, []) if local_user else [],
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


# === RBAC Endpoints ===


@router.patch("/{user_id}/role")
async def update_user_role(
    user_id: str,
    data: UserRoleUpdate,
    admin: dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """
    Aggiorna il ruolo di un utente (solo Admin).

    Args:
        user_id: ID locale dell'utente (non Cognito username)
        data: Nuovo ruolo da assegnare
    """
    # Validate role
    valid_roles = [r.value for r in UserRole]
    if data.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Ruolo non valido. Deve essere uno tra: {', '.join(valid_roles)}",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Prevent admin from demoting themselves
    if user_id == admin.get("user_id") and data.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=400,
            detail="Non puoi modificare il tuo ruolo",
        )

    old_role = user.role
    user.role = data.role
    db.commit()

    logger.info(
        f"User {user.email} role changed from {old_role} to {data.role} "
        f"by admin {admin.get('email')}"
    )

    return {"status": "ok", "old_role": old_role, "new_role": data.role}


@router.put("/{user_id}/repositories")
async def assign_repositories(
    user_id: str,
    data: UserRepoAssign,
    admin: dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Assegna repository a un utente (sostituisce assegnazioni esistenti).

    Args:
        user_id: ID locale dell'utente
        data: Lista di repository UUID da assegnare
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Admin users don't need repo assignments (they see everything)
    if user.role == UserRole.ADMIN.value:
        raise HTTPException(
            status_code=400,
            detail="Gli admin hanno accesso a tutti i repository",
        )

    # Validate that all repos exist
    for repo_id in data.repository_ids:
        repo = db.query(Repository).filter(Repository.id == repo_id).first()
        if not repo:
            raise HTTPException(
                status_code=400,
                detail=f"Repository {repo_id} non trovato",
            )

    # Clear existing assignments
    db.query(UserRepository).filter(UserRepository.user_id == user_id).delete()

    # Add new assignments
    for repo_id in data.repository_ids:
        db.add(UserRepository(user_id=user_id, repository_id=repo_id))

    db.commit()

    logger.info(
        f"User {user.email} assigned to {len(data.repository_ids)} repositories "
        f"by admin {admin.get('email')}"
    )

    return {
        "status": "ok",
        "user_id": user_id,
        "repository_count": len(data.repository_ids),
    }


@router.get("/{user_id}/repositories")
async def get_user_repositories(
    user_id: str,
    admin: dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[str]:
    """
    Ottieni la lista di repository assegnati a un utente.

    Args:
        user_id: ID locale dell'utente
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    access = db.query(UserRepository.repository_id).filter(UserRepository.user_id == user_id).all()
    return [str(a.repository_id) for a in access]
