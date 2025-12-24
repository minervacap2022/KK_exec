"""Credential entity model.

Defines the Credential table for storing encrypted user credentials.
All credential data is Fernet-encrypted at rest.
Credentials are scoped per-user for multi-tenancy security.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlmodel import Column, Field, Relationship, SQLModel, Text

if TYPE_CHECKING:
    from src.models.user import User


def utc_now() -> datetime:
    """Get current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class CredentialBase(SQLModel):
    """Base credential fields shared across models."""

    name: str = Field(
        max_length=255,
        min_length=1,
        description="Human-readable credential name",
    )
    credential_type: str = Field(
        max_length=100,
        description="Type of credential (e.g., 'slack_oauth', 'openai_api_key', 'github_token')",
    )
    mcp_server_id: str | None = Field(
        default=None,
        max_length=100,
        description="Associated MCP server ID if applicable",
    )


class Credential(CredentialBase, table=True):
    """Credential database entity.

    Stores encrypted credential data using Fernet symmetric encryption.
    The encrypted_data field contains a Fernet-encrypted JSON string.

    SECURITY NOTES:
    - Never log decrypted credential values
    - Decrypt only when needed, clear from memory immediately
    - Use constant-time comparison for sensitive operations
    """

    __tablename__ = "credential"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique credential identifier (UUID)",
    )
    user_id: str = Field(
        foreign_key="user.id",
        index=True,
        description="Owner user ID",
    )
    encrypted_data: str = Field(
        sa_column=Column(Text, nullable=False),
        description="Fernet-encrypted JSON credential data",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Creation timestamp (UTC)",
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column_kwargs={"onupdate": utc_now},
        description="Last update timestamp (UTC)",
    )

    # Relationships
    user: "User" = Relationship(back_populates="credentials")


# Standard credential type identifiers
CREDENTIAL_TYPES = {
    # API Keys
    "openai_api_key": {
        "display_name": "OpenAI API Key",
        "fields": ["api_key"],
        "mcp_server_id": None,
    },
    "anthropic_api_key": {
        "display_name": "Anthropic API Key",
        "fields": ["api_key"],
        "mcp_server_id": None,
    },
    # OAuth Tokens
    "slack_oauth": {
        "display_name": "Slack OAuth Token",
        "fields": ["access_token", "refresh_token", "expires_at"],
        "mcp_server_id": "slack",
    },
    "github_token": {
        "display_name": "GitHub Personal Access Token",
        "fields": ["token"],
        "mcp_server_id": "github",
    },
    "notion_oauth": {
        "display_name": "Notion OAuth Token",
        "fields": ["access_token", "refresh_token", "workspace_id", "bot_id"],
        "mcp_server_id": "notion",
    },
    # Generic
    "generic_api_key": {
        "display_name": "Generic API Key",
        "fields": ["api_key", "base_url"],
        "mcp_server_id": None,
    },
}


class CredentialCreate(SQLModel):
    """Schema for creating a new credential.

    The 'data' field contains the raw credential values that will be encrypted.
    """

    name: str = Field(max_length=255, min_length=1)
    credential_type: str = Field(max_length=100)
    data: dict[str, Any] = Field(
        description="Raw credential data (will be encrypted)",
    )
    mcp_server_id: str | None = None


class CredentialUpdate(SQLModel):
    """Schema for updating a credential."""

    name: str | None = Field(default=None, max_length=255)
    data: dict[str, Any] | None = Field(
        default=None,
        description="New credential data (will be encrypted)",
    )


class CredentialRead(CredentialBase):
    """Schema for reading credential data (excludes encrypted data).

    SECURITY: This schema intentionally excludes the encrypted_data field.
    Use CredentialDecrypted only when the actual credential values are needed.
    """

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


class CredentialDecrypted(CredentialRead):
    """Schema for decrypted credential data.

    SECURITY WARNING: This schema exposes decrypted credential values.
    Only use when credential values are actually needed for operations.
    Never log or persist this schema.
    """

    data: dict[str, Any] = Field(
        description="Decrypted credential data",
    )


class CredentialTypeInfo(SQLModel):
    """Schema for credential type information."""

    credential_type: str
    display_name: str
    fields: list[str]
    mcp_server_id: str | None
