"""User entity model.

Defines the User table for authentication and authorization.
All user-specific resources (credentials, workflows, executions) are scoped by user_id.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import EmailStr
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.models.credential import Credential
    from src.models.execution import Execution
    from src.models.workflow import Workflow


def utc_now() -> datetime:
    """Get current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class UserBase(SQLModel):
    """Base user fields shared across models."""

    username: str = Field(
        max_length=50,
        index=True,
        unique=True,
        description="Unique username for login",
    )
    email: EmailStr | None = Field(
        default=None,
        max_length=255,
        index=True,
        description="User email address (optional)",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the user account is active",
    )


class User(UserBase, table=True):
    """User database entity.

    All user data is scoped by user_id for multi-tenancy.
    Passwords are stored as bcrypt hashes, never plaintext.
    """

    __tablename__ = "user"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique user identifier (UUID)",
    )
    hashed_password: str = Field(
        max_length=255,
        description="Bcrypt-hashed password",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Account creation timestamp (UTC)",
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column_kwargs={"onupdate": utc_now},
        description="Last update timestamp (UTC)",
    )

    # Relationships
    credentials: list["Credential"] = Relationship(back_populates="user")
    workflows: list["Workflow"] = Relationship(back_populates="user")
    executions: list["Execution"] = Relationship(back_populates="user")


class UserCreate(SQLModel):
    """Schema for creating a new user."""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    email: EmailStr | None = None


class UserRead(UserBase):
    """Schema for reading user data (excludes sensitive fields)."""

    id: str
    created_at: datetime


class UserLogin(SQLModel):
    """Schema for user login."""

    username: str
    password: str


class Token(SQLModel):
    """JWT token response schema."""

    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    """JWT token payload schema."""

    sub: str  # user_id
    exp: datetime
