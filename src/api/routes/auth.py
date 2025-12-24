"""Authentication routes.

Provides user registration, login, and user info endpoints.
"""

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from src.api.deps import (
    CurrentUser,
    DBSession,
    create_access_token,
    hash_password,
    verify_password,
)
from src.models.user import Token, User, UserCreate, UserLogin, UserRead

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account and return JWT token.",
)
async def register(
    data: UserCreate,
    session: DBSession,
) -> Token:
    """Register a new user.

    Args:
        data: User registration data (username, password)
        session: Database session

    Returns:
        JWT access token

    Raises:
        HTTPException 400: If username already exists
    """
    # Check if username already exists
    query = select(User).where(User.username == data.username)
    result = await session.execute(query)
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        logger.warning(
            "registration_username_exists",
            username=data.username,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Create new user
    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    logger.info(
        "user_registered",
        user_id=user.id,
        username=user.username,
    )

    # Generate token
    access_token = create_access_token(user.id)

    return Token(access_token=access_token)


@router.post(
    "/login",
    response_model=Token,
    summary="Login user",
    description="Authenticate user and return JWT token.",
)
async def login(
    data: UserLogin,
    session: DBSession,
) -> Token:
    """Login user.

    Args:
        data: Login credentials (username, password)
        session: Database session

    Returns:
        JWT access token

    Raises:
        HTTPException 401: If credentials are invalid
    """
    # Find user by username
    query = select(User).where(User.username == data.username)
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning(
            "login_user_not_found",
            username=data.username,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(data.password, user.hashed_password):
        logger.warning(
            "login_invalid_password",
            user_id=user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.is_active:
        logger.warning(
            "login_user_inactive",
            user_id=user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    logger.info(
        "user_logged_in",
        user_id=user.id,
    )

    # Generate token
    access_token = create_access_token(user.id)

    return Token(access_token=access_token)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user",
    description="Get the currently authenticated user's information.",
)
async def get_current_user_info(
    user: CurrentUser,
) -> UserRead:
    """Get current user info.

    Args:
        user: Current authenticated user

    Returns:
        User information
    """
    return UserRead(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at,
    )
