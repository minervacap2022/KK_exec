"""Pytest configuration and fixtures.

Provides common fixtures for all tests including:
- Database sessions
- Test users
- Authentication tokens
- Mock services
"""

import asyncio
from typing import AsyncGenerator, Generator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from src.api.deps import get_db_session, hash_password, create_access_token
from src.config import Settings
from src.main import app
from src.models.user import User
from src.models.workflow import Workflow, WorkflowStatus
from src.models.credential import Credential
from src.core.encryption import CredentialEncryption


# Test database URL (uses SQLite for speed)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create test settings."""
    return Settings(
        database_url=TEST_DATABASE_URL,
        encryption_key="dGVzdC1lbmNyeXB0aW9uLWtleS0zMi1ieXRlcw==",  # Test key
        openai_api_key="sk-test-key",
        jwt_secret_key="test-jwt-secret",
        debug=True,
    )


@pytest_asyncio.fixture
async def db_engine():
    """Create async database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create async database session."""
    async_session_maker = sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""
    # Override database dependency
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        id=str(uuid4()),
        email="test@example.com",
        hashed_password=hash_password("testpassword123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user_token(test_user: User) -> str:
    """Create an access token for test user."""
    return create_access_token(test_user.id)


@pytest_asyncio.fixture
async def auth_headers(test_user_token: str) -> dict[str, str]:
    """Create authentication headers."""
    return {"Authorization": f"Bearer {test_user_token}"}


@pytest_asyncio.fixture
async def test_workflow(db_session: AsyncSession, test_user: User) -> Workflow:
    """Create a test workflow."""
    workflow = Workflow(
        id=str(uuid4()),
        user_id=test_user.id,
        name="Test Workflow",
        description="A test workflow",
        graph='{"version": "1.0", "nodes": [], "edges": [], "config": {}}',
        status=WorkflowStatus.DRAFT,
        version=1,
    )
    db_session.add(workflow)
    await db_session.commit()
    await db_session.refresh(workflow)
    return workflow


@pytest_asyncio.fixture
async def test_credential(
    db_session: AsyncSession,
    test_user: User,
    test_settings: Settings,
) -> Credential:
    """Create a test credential."""
    encryption = CredentialEncryption(test_settings.encryption_key.get_secret_value())
    encrypted_data = encryption.encrypt({"api_key": "test-api-key"})

    credential = Credential(
        id=str(uuid4()),
        user_id=test_user.id,
        name="Test API Key",
        credential_type="openai_api_key",
        encrypted_data=encrypted_data,
    )
    db_session.add(credential)
    await db_session.commit()
    await db_session.refresh(credential)
    return credential


@pytest.fixture
def encryption(test_settings: Settings) -> CredentialEncryption:
    """Create encryption instance."""
    return CredentialEncryption(test_settings.encryption_key.get_secret_value())
