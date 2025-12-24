"""API dependencies for FastAPI dependency injection.

Provides database sessions, user context, and service instances.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, AsyncGenerator

import bcrypt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from src.config import settings
from src.models.user import TokenPayload, User
from src.services.credential_service import CredentialService
from src.services.execution_service import ExecutionService
from src.services.mcp_gateway import MCPGateway
from src.services.workflow_service import WorkflowService

logger = structlog.get_logger()

# Database engine and session
_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
)

_async_session_maker = sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Password hashing uses bcrypt directly

# Security
_bearer_scheme = HTTPBearer(auto_error=False)


async def init_db() -> None:
    """Initialize database tables.

    Only call during development. Use Alembic migrations in production.
    """
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("database_initialized")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session.

    Yields:
        AsyncSession that will be closed after use
    """
    async with _async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


# Type alias for dependency injection
DBSession = Annotated[AsyncSession, Depends(get_db_session)]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def hash_password(password: str) -> str:
    """Hash a password."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def create_access_token(user_id: str) -> str:
    """Create a JWT access token.

    Args:
        user_id: User ID to encode in token

    Returns:
        Encoded JWT token
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )

    payload = TokenPayload(sub=user_id, exp=expire)

    return jwt.encode(
        payload.model_dump(),
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate a JWT access token.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        return TokenPayload(**payload)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: DBSession,
) -> User:
    """Get the current authenticated user.

    Args:
        credentials: Bearer token from request
        session: Database session

    Returns:
        Authenticated user

    Raises:
        HTTPException: If not authenticated or user not found
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_access_token(credentials.credentials)

    # Check token expiration
    if token_data.exp < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user from database
    query = select(User).where(User.id == token_data.sub)
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


# Type alias for authenticated user dependency
CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: DBSession,
) -> User | None:
    """Get the current user if authenticated, None otherwise.

    Args:
        credentials: Bearer token from request
        session: Database session

    Returns:
        Authenticated user or None
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials, session)
    except HTTPException:
        return None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


# Service dependencies
def get_credential_service(session: DBSession) -> CredentialService:
    """Get credential service instance."""
    return CredentialService(session)


def get_workflow_service(session: DBSession) -> WorkflowService:
    """Get workflow service instance."""
    return WorkflowService(session)


def get_execution_service(
    session: DBSession,
    workflow_service: Annotated[WorkflowService, Depends(get_workflow_service)],
    credential_service: Annotated[CredentialService, Depends(get_credential_service)],
) -> ExecutionService:
    """Get execution service instance."""
    return ExecutionService(session, workflow_service, credential_service)


def get_mcp_gateway() -> MCPGateway:
    """Get MCP gateway instance."""
    return MCPGateway()


# Type aliases for service dependencies
CredentialServiceDep = Annotated[CredentialService, Depends(get_credential_service)]
WorkflowServiceDep = Annotated[WorkflowService, Depends(get_workflow_service)]
ExecutionServiceDep = Annotated[ExecutionService, Depends(get_execution_service)]
MCPGatewayDep = Annotated[MCPGateway, Depends(get_mcp_gateway)]
