"""Database connection model for external database viewer."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, String, Text

from turbowrap.db.base import Base

from .base import SoftDeleteMixin, generate_uuid


class DatabaseConnection(Base, SoftDeleteMixin):
    """External database connection for the database viewer.

    Stores connection details for databases that users want to browse/manage.
    Passwords are stored encrypted using Fernet symmetric encryption.
    """

    __tablename__ = "database_connections"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Basic info
    name = Column(String(100), nullable=False)  # User-friendly name
    description = Column(Text, nullable=True)  # Optional description
    db_type = Column(String(20), nullable=False)  # mysql, postgresql, sqlite, etc.

    # Connection details
    host = Column(String(255), nullable=True)  # NULL for SQLite
    port = Column(Integer, nullable=True)  # Default ports: MySQL=3306, PG=5432, etc.
    database = Column(String(255), nullable=False)  # Database name or file path for SQLite
    username = Column(String(100), nullable=True)  # NULL for SQLite
    encrypted_password = Column(Text, nullable=True)  # Fernet encrypted password

    # SSL/TLS Configuration
    ssl_enabled = Column(Boolean, default=False)
    ssl_ca_cert = Column(Text, nullable=True)  # CA certificate content
    ssl_client_cert = Column(Text, nullable=True)  # Client certificate
    ssl_client_key = Column(Text, nullable=True)  # Client private key
    ssl_verify = Column(Boolean, default=True)  # Verify server certificate

    # SSH Tunnel Configuration (for remote databases)
    ssh_enabled = Column(Boolean, default=False)
    ssh_host = Column(String(255), nullable=True)
    ssh_port = Column(Integer, default=22)
    ssh_username = Column(String(100), nullable=True)
    ssh_private_key = Column(Text, nullable=True)  # Encrypted SSH key
    ssh_passphrase = Column(Text, nullable=True)  # Encrypted passphrase

    # Connection options
    connection_timeout = Column(Integer, default=30)  # Seconds
    read_only = Column(Boolean, default=False)  # Read-only mode
    max_connections = Column(Integer, default=5)  # Connection pool size

    # Additional options stored as JSON
    extra_options = Column(JSON, nullable=True)  # Driver-specific options

    # Status tracking
    last_connected_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)  # Last connection error
    is_favorite = Column(Boolean, default=False, index=True)  # Starred connections

    # Organization
    color = Column(String(20), nullable=True)  # Hex color for UI
    icon = Column(String(50), nullable=True)  # Icon identifier
    tags = Column(JSON, nullable=True)  # ["production", "staging", etc.]

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_database_connections_type", "db_type"),
        Index("idx_database_connections_favorite", "is_favorite"),
        Index("idx_database_connections_name", "name"),
    )

    def __repr__(self) -> str:
        return f"<DatabaseConnection {self.name} ({self.db_type})>"
