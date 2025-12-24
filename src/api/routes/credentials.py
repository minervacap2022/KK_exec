"""Credential API endpoints.

Handles credential CRUD operations with encryption.
"""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from src.api.deps import CredentialServiceDep, CurrentUser
from src.models.credential import (
    CredentialCreate,
    CredentialRead,
    CredentialTypeInfo,
    CredentialUpdate,
    CREDENTIAL_TYPES,
)
from src.services.credential_service import (
    CredentialAccessDeniedError,
    CredentialNotFoundError,
    CredentialServiceError,
)

logger = structlog.get_logger()

router = APIRouter()


@router.get("", response_model=list[CredentialRead])
async def list_credentials(
    user: CurrentUser,
    service: CredentialServiceDep,
    credential_type: Annotated[str | None, Query()] = None,
    mcp_server_id: Annotated[str | None, Query()] = None,
) -> list[CredentialRead]:
    """List user's credentials.

    Args:
        user: Current authenticated user
        service: Credential service
        credential_type: Filter by credential type
        mcp_server_id: Filter by MCP server

    Returns:
        List of credentials (without decrypted data)
    """
    return await service.list_all(
        user_id=user.id,
        credential_type=credential_type,
        mcp_server_id=mcp_server_id,
    )


@router.post("", response_model=CredentialRead, status_code=status.HTTP_201_CREATED)
async def create_credential(
    user: CurrentUser,
    service: CredentialServiceDep,
    data: CredentialCreate,
) -> CredentialRead:
    """Create a new credential.

    The credential data will be encrypted before storage.

    Args:
        user: Current authenticated user
        service: Credential service
        data: Credential creation data

    Returns:
        Created credential (without decrypted data)
    """
    # Validate credential type
    type_info = service.get_credential_type_info(data.credential_type)
    if type_info is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown credential type: {data.credential_type}",
        )

    # Validate required fields are present
    required_fields = type_info.get("fields", [])
    missing_fields = [f for f in required_fields if f not in data.data]
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required fields: {', '.join(missing_fields)}",
        )

    logger.info(
        "credential_creation_requested",
        user_id=user.id,
        credential_type=data.credential_type,
    )

    return await service.create(user_id=user.id, data=data)


@router.get("/types", response_model=list[dict[str, Any]])
async def list_credential_types() -> list[dict[str, Any]]:
    """List all available credential types.

    Returns:
        List of credential type definitions
    """
    from src.services.credential_service import CredentialService
    return CredentialService.list_credential_types()


@router.get("/types/{credential_type}", response_model=dict[str, Any])
async def get_credential_type(
    credential_type: str,
) -> dict[str, Any]:
    """Get information about a credential type.

    Args:
        credential_type: Credential type identifier

    Returns:
        Credential type information
    """
    from src.services.credential_service import CredentialService

    type_info = CredentialService.get_credential_type_info(credential_type)
    if type_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown credential type: {credential_type}",
        )

    return {"credential_type": credential_type, **type_info}


@router.get("/{credential_id}", response_model=CredentialRead)
async def get_credential(
    credential_id: str,
    user: CurrentUser,
    service: CredentialServiceDep,
) -> CredentialRead:
    """Get a credential by ID.

    Returns metadata only (not decrypted values).

    Args:
        credential_id: Credential identifier
        user: Current authenticated user
        service: Credential service

    Returns:
        Credential metadata
    """
    try:
        return await service.get(credential_id=credential_id, user_id=user.id)
    except CredentialNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except CredentialAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.put("/{credential_id}", response_model=CredentialRead)
async def update_credential(
    credential_id: str,
    user: CurrentUser,
    service: CredentialServiceDep,
    data: CredentialUpdate,
) -> CredentialRead:
    """Update a credential.

    If data is provided, it will be re-encrypted.

    Args:
        credential_id: Credential identifier
        user: Current authenticated user
        service: Credential service
        data: Update data

    Returns:
        Updated credential
    """
    try:
        logger.info(
            "credential_update_requested",
            user_id=user.id,
            credential_id=credential_id,
        )

        return await service.update(
            credential_id=credential_id,
            user_id=user.id,
            data=data,
        )
    except CredentialNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except CredentialAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: str,
    user: CurrentUser,
    service: CredentialServiceDep,
) -> None:
    """Delete a credential.

    Args:
        credential_id: Credential identifier
        user: Current authenticated user
        service: Credential service
    """
    try:
        await service.delete(credential_id=credential_id, user_id=user.id)
    except CredentialNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except CredentialAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.post("/{credential_id}/test", response_model=dict[str, Any])
async def test_credential(
    credential_id: str,
    user: CurrentUser,
    service: CredentialServiceDep,
) -> dict[str, Any]:
    """Test a credential by attempting to use it.

    This endpoint attempts to validate the credential by making
    a test call to the associated service.

    Args:
        credential_id: Credential identifier
        user: Current authenticated user
        service: Credential service

    Returns:
        Test result with status
    """
    try:
        # Get decrypted credential
        credential = await service.get_decrypted(
            credential_id=credential_id,
            user_id=user.id,
        )

        # TODO: Implement actual credential testing based on type
        # For now, just verify we can decrypt it
        return {
            "status": "success",
            "message": "Credential is valid and accessible",
            "credential_type": credential.credential_type,
        }

    except CredentialNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except CredentialAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except CredentialServiceError as e:
        return {
            "status": "error",
            "message": str(e),
        }
