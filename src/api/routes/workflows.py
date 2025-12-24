"""Workflow API endpoints.

Handles workflow CRUD operations and NLP-based workflow building.
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from src.api.deps import (
    CredentialServiceDep,
    CurrentUser,
    WorkflowServiceDep,
)
from src.models.workflow import (
    WorkflowBuildRequest,
    WorkflowCreate,
    WorkflowRead,
    WorkflowStatus,
    WorkflowUpdate,
)
from src.services.workflow_service import (
    WorkflowAccessDeniedError,
    WorkflowNotFoundError,
    WorkflowServiceError,
    WorkflowValidationError,
)

logger = structlog.get_logger()

router = APIRouter()


@router.get("", response_model=list[WorkflowRead])
async def list_workflows(
    user: CurrentUser,
    service: WorkflowServiceDep,
    status_filter: Annotated[WorkflowStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WorkflowRead]:
    """List user's workflows.

    Args:
        user: Current authenticated user
        service: Workflow service
        status_filter: Filter by workflow status
        limit: Maximum number of results
        offset: Pagination offset

    Returns:
        List of workflows
    """
    return await service.list_all(
        user_id=user.id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    user: CurrentUser,
    service: WorkflowServiceDep,
    data: WorkflowCreate,
) -> WorkflowRead:
    """Create a new workflow.

    Args:
        user: Current authenticated user
        service: Workflow service
        data: Workflow creation data

    Returns:
        Created workflow
    """
    try:
        return await service.create(user_id=user.id, data=data)
    except WorkflowValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(e), "errors": e.errors},
        ) from e


@router.post("/build", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def build_workflow(
    user: CurrentUser,
    workflow_service: WorkflowServiceDep,
    credential_service: CredentialServiceDep,
    data: WorkflowBuildRequest,
) -> WorkflowRead:
    """Build a workflow from natural language prompt.

    The LLM will analyze the prompt and generate a complete workflow
    with appropriate nodes and connections.

    Args:
        user: Current authenticated user
        workflow_service: Workflow service
        credential_service: Credential service
        data: Build request with prompt

    Returns:
        Generated workflow
    """
    try:
        # Get user's available credential types
        available_credentials = await credential_service.get_available_types(user.id)

        # Override with request-specified credentials if provided
        if data.available_credentials is not None:
            # Filter to only credentials the user actually has
            available_credentials = [
                c for c in data.available_credentials if c in available_credentials
            ]

        logger.info(
            "workflow_build_requested",
            user_id=user.id,
            prompt_length=len(data.prompt),
            available_credentials=available_credentials,
        )

        return await workflow_service.build_from_prompt(
            user_id=user.id,
            prompt=data.prompt,
            available_credentials=available_credentials,
        )
    except WorkflowServiceError as e:
        logger.error(
            "workflow_build_failed",
            user_id=user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: str,
    user: CurrentUser,
    service: WorkflowServiceDep,
) -> WorkflowRead:
    """Get a workflow by ID.

    Args:
        workflow_id: Workflow identifier
        user: Current authenticated user
        service: Workflow service

    Returns:
        Workflow data
    """
    try:
        return await service.get(workflow_id=workflow_id, user_id=user.id)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except WorkflowAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.put("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: str,
    user: CurrentUser,
    service: WorkflowServiceDep,
    data: WorkflowUpdate,
) -> WorkflowRead:
    """Update a workflow.

    Args:
        workflow_id: Workflow identifier
        user: Current authenticated user
        service: Workflow service
        data: Update data

    Returns:
        Updated workflow
    """
    try:
        return await service.update(
            workflow_id=workflow_id,
            user_id=user.id,
            data=data,
        )
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except WorkflowAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except WorkflowValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(e), "errors": e.errors},
        ) from e


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    user: CurrentUser,
    service: WorkflowServiceDep,
) -> None:
    """Delete a workflow.

    Args:
        workflow_id: Workflow identifier
        user: Current authenticated user
        service: Workflow service
    """
    try:
        await service.delete(workflow_id=workflow_id, user_id=user.id)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except WorkflowAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.post("/{workflow_id}/activate", response_model=WorkflowRead)
async def activate_workflow(
    workflow_id: str,
    user: CurrentUser,
    service: WorkflowServiceDep,
) -> WorkflowRead:
    """Activate a workflow.

    Args:
        workflow_id: Workflow identifier
        user: Current authenticated user
        service: Workflow service

    Returns:
        Updated workflow
    """
    try:
        return await service.activate(workflow_id=workflow_id, user_id=user.id)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except WorkflowAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.post("/{workflow_id}/archive", response_model=WorkflowRead)
async def archive_workflow(
    workflow_id: str,
    user: CurrentUser,
    service: WorkflowServiceDep,
) -> WorkflowRead:
    """Archive a workflow.

    Args:
        workflow_id: Workflow identifier
        user: Current authenticated user
        service: Workflow service

    Returns:
        Updated workflow
    """
    try:
        return await service.archive(workflow_id=workflow_id, user_id=user.id)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except WorkflowAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.post("/{workflow_id}/duplicate", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def duplicate_workflow(
    workflow_id: str,
    user: CurrentUser,
    service: WorkflowServiceDep,
    new_name: Annotated[str | None, Query(max_length=255)] = None,
) -> WorkflowRead:
    """Duplicate a workflow.

    Args:
        workflow_id: Source workflow identifier
        user: Current authenticated user
        service: Workflow service
        new_name: Name for the copy (optional)

    Returns:
        New workflow copy
    """
    try:
        return await service.duplicate(
            workflow_id=workflow_id,
            user_id=user.id,
            new_name=new_name,
        )
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except WorkflowAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
