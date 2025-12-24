"""Credential service.

Handles CRUD operations for user credentials with encryption.
All credential data is Fernet-encrypted at rest.
"""

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.encryption import CredentialEncryption, DecryptionError, mask_credential_value
from src.models.credential import (
    Credential,
    CredentialCreate,
    CredentialDecrypted,
    CredentialRead,
    CredentialUpdate,
    CREDENTIAL_TYPES,
)

logger = structlog.get_logger()


class CredentialServiceError(Exception):
    """Error in credential service operations."""

    pass


class CredentialNotFoundError(CredentialServiceError):
    """Credential not found."""

    pass


class CredentialAccessDeniedError(CredentialServiceError):
    """User doesn't have access to credential."""

    pass


class CredentialService:
    """Service for managing user credentials.

    Handles:
    - Creating credentials with encryption
    - Reading credentials (encrypted or decrypted)
    - Updating credential data
    - Deleting credentials
    - User-scoped access control

    Example usage:
        service = CredentialService(session)

        # Create credential
        cred = await service.create(
            user_id="user-123",
            data=CredentialCreate(
                name="My Slack Token",
                credential_type="slack_oauth",
                data={"access_token": "xoxp-..."}
            )
        )

        # Get decrypted credential
        decrypted = await service.get_decrypted(
            credential_id=cred.id,
            user_id="user-123"
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize credential service.

        Args:
            session: Async database session
        """
        self._session = session
        self._encryption = CredentialEncryption(
            settings.encryption_key.get_secret_value()
        )

    async def create(
        self,
        user_id: str,
        data: CredentialCreate,
    ) -> CredentialRead:
        """Create a new credential.

        Args:
            user_id: Owner user ID
            data: Credential creation data

        Returns:
            Created credential (without decrypted data)
        """
        # Encrypt credential data
        encrypted_data = self._encryption.encrypt(data.data)

        # Create credential entity
        credential = Credential(
            user_id=user_id,
            name=data.name,
            credential_type=data.credential_type,
            encrypted_data=encrypted_data,
            mcp_server_id=data.mcp_server_id,
        )

        self._session.add(credential)
        await self._session.commit()
        await self._session.refresh(credential)

        logger.info(
            "credential_created",
            credential_id=credential.id,
            user_id=user_id,
            credential_type=data.credential_type,
        )

        return CredentialRead.model_validate(credential)

    async def get(
        self,
        credential_id: str,
        user_id: str,
    ) -> CredentialRead:
        """Get a credential (without decrypted data).

        Args:
            credential_id: Credential ID
            user_id: Requesting user ID

        Returns:
            Credential metadata

        Raises:
            CredentialNotFoundError: If credential doesn't exist
            CredentialAccessDeniedError: If user doesn't own credential
        """
        credential = await self._get_and_verify(credential_id, user_id)
        return CredentialRead.model_validate(credential)

    async def get_decrypted(
        self,
        credential_id: str,
        user_id: str,
    ) -> CredentialDecrypted:
        """Get a credential with decrypted data.

        SECURITY: Only call when decrypted values are actually needed.
        Never log the returned data.

        Args:
            credential_id: Credential ID
            user_id: Requesting user ID

        Returns:
            Credential with decrypted data

        Raises:
            CredentialNotFoundError: If credential doesn't exist
            CredentialAccessDeniedError: If user doesn't own credential
            CredentialServiceError: If decryption fails
        """
        credential = await self._get_and_verify(credential_id, user_id)

        try:
            decrypted_data = self._encryption.decrypt(credential.encrypted_data)
        except DecryptionError as e:
            logger.error(
                "credential_decryption_failed",
                credential_id=credential_id,
                user_id=user_id,
            )
            raise CredentialServiceError("Failed to decrypt credential") from e

        logger.debug(
            "credential_decrypted",
            credential_id=credential_id,
            user_id=user_id,
        )

        return CredentialDecrypted(
            id=credential.id,
            user_id=credential.user_id,
            name=credential.name,
            credential_type=credential.credential_type,
            mcp_server_id=credential.mcp_server_id,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
            data=decrypted_data,
        )

    async def list_all(
        self,
        user_id: str,
        credential_type: str | None = None,
        mcp_server_id: str | None = None,
    ) -> list[CredentialRead]:
        """List user's credentials.

        Args:
            user_id: User ID
            credential_type: Filter by credential type
            mcp_server_id: Filter by MCP server

        Returns:
            List of credentials (without decrypted data)
        """
        query = select(Credential).where(Credential.user_id == user_id)

        if credential_type:
            query = query.where(Credential.credential_type == credential_type)
        if mcp_server_id:
            query = query.where(Credential.mcp_server_id == mcp_server_id)

        result = await self._session.execute(query)
        credentials = result.scalars().all()

        return [CredentialRead.model_validate(c) for c in credentials]

    async def list_all_decrypted(
        self,
        user_id: str,
        credential_type: str | None = None,
    ) -> list[CredentialDecrypted]:
        """List user's credentials with decrypted data.

        SECURITY: Only call when decrypted values are needed for execution.

        Args:
            user_id: User ID
            credential_type: Filter by credential type

        Returns:
            List of credentials with decrypted data
        """
        query = select(Credential).where(Credential.user_id == user_id)

        if credential_type:
            query = query.where(Credential.credential_type == credential_type)

        result = await self._session.execute(query)
        credentials = result.scalars().all()

        decrypted_list = []
        for cred in credentials:
            try:
                decrypted_data = self._encryption.decrypt(cred.encrypted_data)
                decrypted_list.append(
                    CredentialDecrypted(
                        id=cred.id,
                        user_id=cred.user_id,
                        name=cred.name,
                        credential_type=cred.credential_type,
                        mcp_server_id=cred.mcp_server_id,
                        created_at=cred.created_at,
                        updated_at=cred.updated_at,
                        data=decrypted_data,
                    )
                )
            except Exception as e:
                logger.error(
                    "credential_decryption_failed",
                    credential_id=cred.id,
                    error=str(e),
                )

        return decrypted_list

    async def update(
        self,
        credential_id: str,
        user_id: str,
        data: CredentialUpdate,
    ) -> CredentialRead:
        """Update a credential.

        Args:
            credential_id: Credential ID
            user_id: Requesting user ID
            data: Update data

        Returns:
            Updated credential

        Raises:
            CredentialNotFoundError: If credential doesn't exist
            CredentialAccessDeniedError: If user doesn't own credential
        """
        credential = await self._get_and_verify(credential_id, user_id)

        if data.name is not None:
            credential.name = data.name

        if data.data is not None:
            credential.encrypted_data = self._encryption.encrypt(data.data)

        await self._session.commit()
        await self._session.refresh(credential)

        logger.info(
            "credential_updated",
            credential_id=credential_id,
            user_id=user_id,
        )

        return CredentialRead.model_validate(credential)

    async def delete(
        self,
        credential_id: str,
        user_id: str,
    ) -> None:
        """Delete a credential.

        Args:
            credential_id: Credential ID
            user_id: Requesting user ID

        Raises:
            CredentialNotFoundError: If credential doesn't exist
            CredentialAccessDeniedError: If user doesn't own credential
        """
        credential = await self._get_and_verify(credential_id, user_id)

        await self._session.delete(credential)
        await self._session.commit()

        logger.info(
            "credential_deleted",
            credential_id=credential_id,
            user_id=user_id,
        )

    async def get_for_mcp_server(
        self,
        user_id: str,
        mcp_server_id: str,
    ) -> CredentialDecrypted | None:
        """Get decrypted credential for an MCP server.

        Args:
            user_id: User ID
            mcp_server_id: MCP server ID

        Returns:
            Decrypted credential or None
        """
        query = (
            select(Credential)
            .where(Credential.user_id == user_id)
            .where(Credential.mcp_server_id == mcp_server_id)
        )
        result = await self._session.execute(query)
        credential = result.scalar_one_or_none()

        if credential is None:
            return None

        try:
            decrypted_data = self._encryption.decrypt(credential.encrypted_data)
        except DecryptionError:
            logger.error(
                "credential_decryption_failed",
                mcp_server_id=mcp_server_id,
                user_id=user_id,
            )
            return None

        return CredentialDecrypted(
            id=credential.id,
            user_id=credential.user_id,
            name=credential.name,
            credential_type=credential.credential_type,
            mcp_server_id=credential.mcp_server_id,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
            data=decrypted_data,
        )

    async def get_available_types(self, user_id: str) -> list[str]:
        """Get credential types the user has configured.

        Args:
            user_id: User ID

        Returns:
            List of credential type identifiers
        """
        query = select(Credential.credential_type).where(
            Credential.user_id == user_id
        ).distinct()
        result = await self._session.execute(query)
        return [row[0] for row in result.fetchall()]

    async def _get_and_verify(
        self,
        credential_id: str,
        user_id: str,
    ) -> Credential:
        """Get credential and verify ownership.

        Args:
            credential_id: Credential ID
            user_id: Expected owner ID

        Returns:
            Credential entity

        Raises:
            CredentialNotFoundError: If not found
            CredentialAccessDeniedError: If wrong owner
        """
        query = select(Credential).where(Credential.id == credential_id)
        result = await self._session.execute(query)
        credential = result.scalar_one_or_none()

        if credential is None:
            raise CredentialNotFoundError(f"Credential '{credential_id}' not found")

        if credential.user_id != user_id:
            logger.warning(
                "credential_access_denied",
                credential_id=credential_id,
                requested_by=user_id,
                owner=credential.user_id,
            )
            raise CredentialAccessDeniedError("Access denied to credential")

        return credential

    @staticmethod
    def get_credential_type_info(credential_type: str) -> dict[str, Any] | None:
        """Get information about a credential type.

        Args:
            credential_type: Credential type identifier

        Returns:
            Type information or None
        """
        return CREDENTIAL_TYPES.get(credential_type)

    @staticmethod
    def list_credential_types() -> list[dict[str, Any]]:
        """List all available credential types.

        Returns:
            List of credential type information
        """
        return [
            {"credential_type": key, **value}
            for key, value in CREDENTIAL_TYPES.items()
        ]
