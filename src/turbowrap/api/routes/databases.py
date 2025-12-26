"""Database connection management routes."""

import base64
import os
from datetime import datetime
from typing import Literal

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.models import DatabaseConnection, DatabaseType, generate_uuid
from ..deps import get_db

router = APIRouter(prefix="/databases", tags=["databases"])

# Encryption key - in production, this should be from environment variable
# Generate once and store securely: Fernet.generate_key().decode()
_ENCRYPTION_KEY = os.environ.get("TURBOWRAP_DB_ENCRYPTION_KEY")


def _get_fernet() -> Fernet | None:
    """Get Fernet instance for encryption/decryption."""
    if not _ENCRYPTION_KEY:
        return None
    try:
        return Fernet(_ENCRYPTION_KEY.encode())
    except Exception:
        return None


def _encrypt_password(password: str | None) -> str | None:
    """Encrypt a password for storage."""
    if not password:
        return None
    fernet = _get_fernet()
    if fernet:
        return fernet.encrypt(password.encode()).decode()
    # Fallback: base64 encode (NOT secure, just obfuscation)
    return base64.b64encode(password.encode()).decode()


def _decrypt_password(encrypted: str | None) -> str | None:
    """Decrypt a stored password."""
    if not encrypted:
        return None
    fernet = _get_fernet()
    if fernet:
        try:
            return fernet.decrypt(encrypted.encode()).decode()
        except Exception:
            pass
    # Fallback: try base64 decode
    try:
        return base64.b64decode(encrypted.encode()).decode()
    except Exception:
        return None


# --- Pydantic Schemas ---


class SSLConfig(BaseModel):
    """SSL/TLS configuration."""

    enabled: bool = False
    ca_cert: str | None = None
    client_cert: str | None = None
    client_key: str | None = None
    verify: bool = True


class SSHConfig(BaseModel):
    """SSH tunnel configuration."""

    enabled: bool = False
    host: str | None = None
    port: int = 22
    username: str | None = None
    private_key: str | None = None
    passphrase: str | None = None


class DatabaseConnectionCreate(BaseModel):
    """Request schema for creating a database connection."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    db_type: Literal["mysql", "postgresql", "sqlite", "mongodb", "redis", "mariadb", "mssql"]

    # Connection details
    host: str | None = None
    port: int | None = None
    database: str = Field(..., min_length=1)
    username: str | None = None
    password: str | None = None  # Will be encrypted before storage

    # SSL configuration
    ssl: SSLConfig | None = None

    # SSH tunnel configuration
    ssh: SSHConfig | None = None

    # Options
    connection_timeout: int = Field(default=30, ge=1, le=300)
    read_only: bool = False
    max_connections: int = Field(default=5, ge=1, le=100)
    extra_options: dict | None = None

    # Organization
    color: str | None = None
    icon: str | None = None
    tags: list[str] | None = None
    is_favorite: bool = False


class DatabaseConnectionUpdate(BaseModel):
    """Request schema for updating a database connection."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    db_type: Literal["mysql", "postgresql", "sqlite", "mongodb", "redis", "mariadb", "mssql"] | None = None

    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None  # Set to empty string to clear, None to keep existing

    ssl: SSLConfig | None = None
    ssh: SSHConfig | None = None

    connection_timeout: int | None = Field(default=None, ge=1, le=300)
    read_only: bool | None = None
    max_connections: int | None = Field(default=None, ge=1, le=100)
    extra_options: dict | None = None

    color: str | None = None
    icon: str | None = None
    tags: list[str] | None = None
    is_favorite: bool | None = None


class DatabaseConnectionResponse(BaseModel):
    """Response schema for database connection."""

    id: str
    name: str
    description: str | None
    db_type: str

    host: str | None
    port: int | None
    database: str
    username: str | None
    has_password: bool  # Don't expose password, just indicate if set

    ssl_enabled: bool
    ssh_enabled: bool

    connection_timeout: int
    read_only: bool
    max_connections: int
    extra_options: dict | None

    last_connected_at: datetime | None
    last_error: str | None
    is_favorite: bool

    color: str | None
    icon: str | None
    tags: list[str] | None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TestConnectionRequest(BaseModel):
    """Request to test a connection (either existing or new)."""

    # Either provide connection_id OR full connection details
    connection_id: str | None = None

    # Or provide connection details directly
    db_type: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    ssl: SSLConfig | None = None
    ssh: SSHConfig | None = None


class TestConnectionResponse(BaseModel):
    """Response from connection test."""

    success: bool
    message: str
    latency_ms: int | None = None
    server_version: str | None = None
    database_size: str | None = None


# --- Helper Functions ---


def _get_default_port(db_type: str) -> int | None:
    """Get default port for database type."""
    defaults = {
        "mysql": 3306,
        "mariadb": 3306,
        "postgresql": 5432,
        "mongodb": 27017,
        "redis": 6379,
        "mssql": 1433,
    }
    return defaults.get(db_type)


def _model_to_response(conn: DatabaseConnection) -> DatabaseConnectionResponse:
    """Convert model to response schema."""
    return DatabaseConnectionResponse(
        id=conn.id,
        name=conn.name,
        description=conn.description,
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database=conn.database,
        username=conn.username,
        has_password=bool(conn.encrypted_password),
        ssl_enabled=conn.ssl_enabled or False,
        ssh_enabled=conn.ssh_enabled or False,
        connection_timeout=conn.connection_timeout or 30,
        read_only=conn.read_only or False,
        max_connections=conn.max_connections or 5,
        extra_options=conn.extra_options,
        last_connected_at=conn.last_connected_at,
        last_error=conn.last_error,
        is_favorite=conn.is_favorite or False,
        color=conn.color,
        icon=conn.icon,
        tags=conn.tags,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


# --- Routes ---


@router.get("", response_model=list[DatabaseConnectionResponse])
def list_connections(
    db_type: str | None = None,
    favorites_only: bool = False,
    db: Session = Depends(get_db),
):
    """List all database connections."""
    query = db.query(DatabaseConnection).filter(DatabaseConnection.deleted_at.is_(None))

    if db_type:
        query = query.filter(DatabaseConnection.db_type == db_type)
    if favorites_only:
        query = query.filter(DatabaseConnection.is_favorite == True)  # noqa: E712

    query = query.order_by(
        DatabaseConnection.is_favorite.desc(),
        DatabaseConnection.name.asc(),
    )

    connections = query.all()
    return [_model_to_response(c) for c in connections]


@router.get("/{connection_id}", response_model=DatabaseConnectionResponse)
def get_connection(connection_id: str, db: Session = Depends(get_db)):
    """Get a specific database connection."""
    conn = (
        db.query(DatabaseConnection)
        .filter(
            DatabaseConnection.id == connection_id,
            DatabaseConnection.deleted_at.is_(None),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Database connection not found")
    return _model_to_response(conn)


@router.post("", response_model=DatabaseConnectionResponse)
def create_connection(
    req: DatabaseConnectionCreate,
    db: Session = Depends(get_db),
):
    """Create a new database connection."""
    # Set default port if not provided
    port = req.port or _get_default_port(req.db_type)

    conn = DatabaseConnection(
        id=generate_uuid(),
        name=req.name,
        description=req.description,
        db_type=req.db_type,
        host=req.host,
        port=port,
        database=req.database,
        username=req.username,
        encrypted_password=_encrypt_password(req.password),
        # SSL
        ssl_enabled=req.ssl.enabled if req.ssl else False,
        ssl_ca_cert=req.ssl.ca_cert if req.ssl else None,
        ssl_client_cert=req.ssl.client_cert if req.ssl else None,
        ssl_client_key=req.ssl.client_key if req.ssl else None,
        ssl_verify=req.ssl.verify if req.ssl else True,
        # SSH
        ssh_enabled=req.ssh.enabled if req.ssh else False,
        ssh_host=req.ssh.host if req.ssh else None,
        ssh_port=req.ssh.port if req.ssh else 22,
        ssh_username=req.ssh.username if req.ssh else None,
        ssh_private_key=_encrypt_password(req.ssh.private_key) if req.ssh and req.ssh.private_key else None,
        ssh_passphrase=_encrypt_password(req.ssh.passphrase) if req.ssh and req.ssh.passphrase else None,
        # Options
        connection_timeout=req.connection_timeout,
        read_only=req.read_only,
        max_connections=req.max_connections,
        extra_options=req.extra_options,
        # Organization
        color=req.color,
        icon=req.icon,
        tags=req.tags,
        is_favorite=req.is_favorite,
    )

    db.add(conn)
    db.commit()
    db.refresh(conn)

    return _model_to_response(conn)


@router.put("/{connection_id}", response_model=DatabaseConnectionResponse)
def update_connection(
    connection_id: str,
    req: DatabaseConnectionUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing database connection."""
    conn = (
        db.query(DatabaseConnection)
        .filter(
            DatabaseConnection.id == connection_id,
            DatabaseConnection.deleted_at.is_(None),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Database connection not found")

    # Update fields if provided
    if req.name is not None:
        conn.name = req.name
    if req.description is not None:
        conn.description = req.description
    if req.db_type is not None:
        conn.db_type = req.db_type
    if req.host is not None:
        conn.host = req.host
    if req.port is not None:
        conn.port = req.port
    if req.database is not None:
        conn.database = req.database
    if req.username is not None:
        conn.username = req.username

    # Password: if explicitly set (even to empty string), update it
    if req.password is not None:
        conn.encrypted_password = _encrypt_password(req.password) if req.password else None

    # SSL configuration
    if req.ssl is not None:
        conn.ssl_enabled = req.ssl.enabled
        conn.ssl_ca_cert = req.ssl.ca_cert
        conn.ssl_client_cert = req.ssl.client_cert
        conn.ssl_client_key = req.ssl.client_key
        conn.ssl_verify = req.ssl.verify

    # SSH configuration
    if req.ssh is not None:
        conn.ssh_enabled = req.ssh.enabled
        conn.ssh_host = req.ssh.host
        conn.ssh_port = req.ssh.port
        conn.ssh_username = req.ssh.username
        if req.ssh.private_key is not None:
            conn.ssh_private_key = _encrypt_password(req.ssh.private_key) if req.ssh.private_key else None
        if req.ssh.passphrase is not None:
            conn.ssh_passphrase = _encrypt_password(req.ssh.passphrase) if req.ssh.passphrase else None

    # Options
    if req.connection_timeout is not None:
        conn.connection_timeout = req.connection_timeout
    if req.read_only is not None:
        conn.read_only = req.read_only
    if req.max_connections is not None:
        conn.max_connections = req.max_connections
    if req.extra_options is not None:
        conn.extra_options = req.extra_options

    # Organization
    if req.color is not None:
        conn.color = req.color
    if req.icon is not None:
        conn.icon = req.icon
    if req.tags is not None:
        conn.tags = req.tags
    if req.is_favorite is not None:
        conn.is_favorite = req.is_favorite

    conn.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conn)

    return _model_to_response(conn)


@router.delete("/{connection_id}")
def delete_connection(connection_id: str, db: Session = Depends(get_db)):
    """Delete a database connection (soft delete)."""
    conn = (
        db.query(DatabaseConnection)
        .filter(
            DatabaseConnection.id == connection_id,
            DatabaseConnection.deleted_at.is_(None),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Database connection not found")

    conn.soft_delete()
    db.commit()

    return {"status": "deleted", "id": connection_id}


@router.post("/{connection_id}/favorite")
def toggle_favorite(connection_id: str, db: Session = Depends(get_db)):
    """Toggle favorite status of a connection."""
    conn = (
        db.query(DatabaseConnection)
        .filter(
            DatabaseConnection.id == connection_id,
            DatabaseConnection.deleted_at.is_(None),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Database connection not found")

    conn.is_favorite = not conn.is_favorite
    conn.updated_at = datetime.utcnow()
    db.commit()

    return {"is_favorite": conn.is_favorite}


@router.post("/{connection_id}/duplicate", response_model=DatabaseConnectionResponse)
def duplicate_connection(connection_id: str, db: Session = Depends(get_db)):
    """Duplicate an existing connection."""
    original = (
        db.query(DatabaseConnection)
        .filter(
            DatabaseConnection.id == connection_id,
            DatabaseConnection.deleted_at.is_(None),
        )
        .first()
    )
    if not original:
        raise HTTPException(status_code=404, detail="Database connection not found")

    # Create a copy with new ID and modified name
    new_conn = DatabaseConnection(
        id=generate_uuid(),
        name=f"{original.name} (Copy)",
        description=original.description,
        db_type=original.db_type,
        host=original.host,
        port=original.port,
        database=original.database,
        username=original.username,
        encrypted_password=original.encrypted_password,
        ssl_enabled=original.ssl_enabled,
        ssl_ca_cert=original.ssl_ca_cert,
        ssl_client_cert=original.ssl_client_cert,
        ssl_client_key=original.ssl_client_key,
        ssl_verify=original.ssl_verify,
        ssh_enabled=original.ssh_enabled,
        ssh_host=original.ssh_host,
        ssh_port=original.ssh_port,
        ssh_username=original.ssh_username,
        ssh_private_key=original.ssh_private_key,
        ssh_passphrase=original.ssh_passphrase,
        connection_timeout=original.connection_timeout,
        read_only=original.read_only,
        max_connections=original.max_connections,
        extra_options=original.extra_options,
        color=original.color,
        icon=original.icon,
        tags=original.tags,
        is_favorite=False,  # Don't copy favorite status
    )

    db.add(new_conn)
    db.commit()
    db.refresh(new_conn)

    return _model_to_response(new_conn)


@router.post("/test", response_model=TestConnectionResponse)
async def test_connection(req: TestConnectionRequest, db: Session = Depends(get_db)):
    """Test a database connection.

    Can test either an existing saved connection (by ID) or test new connection details.
    """
    import time

    # Get connection details
    if req.connection_id:
        conn = (
            db.query(DatabaseConnection)
            .filter(
                DatabaseConnection.id == req.connection_id,
                DatabaseConnection.deleted_at.is_(None),
            )
            .first()
        )
        if not conn:
            raise HTTPException(status_code=404, detail="Database connection not found")

        db_type = conn.db_type
        host = conn.host
        port = conn.port
        database = conn.database
        username = conn.username
        password = _decrypt_password(conn.encrypted_password)
    else:
        if not req.db_type or not req.database:
            raise HTTPException(
                status_code=400,
                detail="Either connection_id or db_type+database required",
            )
        db_type = req.db_type
        host = req.host
        port = req.port or _get_default_port(db_type)
        database = req.database
        username = req.username
        password = req.password

    start_time = time.time()

    try:
        # Test connection based on database type
        if db_type == "sqlite":
            import sqlite3

            conn_test = sqlite3.connect(database, timeout=5)
            cursor = conn_test.cursor()
            cursor.execute("SELECT sqlite_version()")
            version = cursor.fetchone()[0]
            conn_test.close()

            latency = int((time.time() - start_time) * 1000)
            return TestConnectionResponse(
                success=True,
                message="Connection successful",
                latency_ms=latency,
                server_version=f"SQLite {version}",
            )

        elif db_type in ("mysql", "mariadb"):
            import pymysql

            conn_test = pymysql.connect(
                host=host,
                port=port or 3306,
                user=username,
                password=password or "",
                database=database,
                connect_timeout=5,
            )
            cursor = conn_test.cursor()
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            conn_test.close()

            latency = int((time.time() - start_time) * 1000)
            return TestConnectionResponse(
                success=True,
                message="Connection successful",
                latency_ms=latency,
                server_version=version,
            )

        elif db_type == "postgresql":
            import psycopg2

            conn_test = psycopg2.connect(
                host=host,
                port=port or 5432,
                user=username,
                password=password or "",
                dbname=database,
                connect_timeout=5,
            )
            cursor = conn_test.cursor()
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
            conn_test.close()

            latency = int((time.time() - start_time) * 1000)
            return TestConnectionResponse(
                success=True,
                message="Connection successful",
                latency_ms=latency,
                server_version=version.split(",")[0] if version else None,
            )

        elif db_type == "mongodb":
            from pymongo import MongoClient

            uri = f"mongodb://{username}:{password}@{host}:{port or 27017}/{database}" if username else f"mongodb://{host}:{port or 27017}/{database}"
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            info = client.server_info()
            client.close()

            latency = int((time.time() - start_time) * 1000)
            return TestConnectionResponse(
                success=True,
                message="Connection successful",
                latency_ms=latency,
                server_version=info.get("version"),
            )

        elif db_type == "redis":
            import redis

            r = redis.Redis(
                host=host or "localhost",
                port=port or 6379,
                password=password,
                db=int(database) if database.isdigit() else 0,
                socket_timeout=5,
            )
            info = r.info()
            r.close()

            latency = int((time.time() - start_time) * 1000)
            return TestConnectionResponse(
                success=True,
                message="Connection successful",
                latency_ms=latency,
                server_version=info.get("redis_version"),
            )

        else:
            return TestConnectionResponse(
                success=False,
                message=f"Database type '{db_type}' not yet supported for testing",
            )

    except ImportError as e:
        return TestConnectionResponse(
            success=False,
            message=f"Missing driver: {str(e)}. Install the required package.",
        )
    except Exception as e:
        # Update last_error if testing existing connection
        if req.connection_id:
            conn = db.query(DatabaseConnection).filter(DatabaseConnection.id == req.connection_id).first()
            if conn:
                conn.last_error = str(e)
                conn.updated_at = datetime.utcnow()
                db.commit()

        return TestConnectionResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


@router.get("/types/supported")
def get_supported_types():
    """Get list of supported database types with metadata."""
    return [
        {
            "type": "mysql",
            "name": "MySQL",
            "icon": "mysql",
            "default_port": 3306,
            "supports_ssl": True,
            "supports_ssh": True,
        },
        {
            "type": "postgresql",
            "name": "PostgreSQL",
            "icon": "postgresql",
            "default_port": 5432,
            "supports_ssl": True,
            "supports_ssh": True,
        },
        {
            "type": "sqlite",
            "name": "SQLite",
            "icon": "sqlite",
            "default_port": None,
            "supports_ssl": False,
            "supports_ssh": False,
            "file_based": True,
        },
        {
            "type": "mongodb",
            "name": "MongoDB",
            "icon": "mongodb",
            "default_port": 27017,
            "supports_ssl": True,
            "supports_ssh": True,
        },
        {
            "type": "redis",
            "name": "Redis",
            "icon": "redis",
            "default_port": 6379,
            "supports_ssl": True,
            "supports_ssh": True,
        },
        {
            "type": "mariadb",
            "name": "MariaDB",
            "icon": "mariadb",
            "default_port": 3306,
            "supports_ssl": True,
            "supports_ssh": True,
        },
        {
            "type": "mssql",
            "name": "SQL Server",
            "icon": "sqlserver",
            "default_port": 1433,
            "supports_ssl": True,
            "supports_ssh": True,
        },
    ]
