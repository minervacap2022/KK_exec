"""Execution API endpoints.

Handles workflow execution and SSE streaming.
"""

import json
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from sse_starlette.sse import EventSourceResponse

from src.api.deps import CurrentUser, ExecutionServiceDep
from src.models.execution import (
    ExecutionCreate,
    ExecutionRead,
    ExecutionStatus,
)
from src.services.execution_service import (
    ExecutionAccessDeniedError,
    ExecutionNotFoundError,
    ExecutionServiceError,
)

logger = structlog.get_logger()

router = APIRouter()


@router.get("", response_model=list[ExecutionRead])
async def list_executions(
    user: CurrentUser,
    service: ExecutionServiceDep,
    workflow_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[ExecutionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExecutionRead]:
    """List user's executions.

    Args:
        user: Current authenticated user
        service: Execution service
        workflow_id: Filter by workflow
        status_filter: Filter by status
        limit: Maximum results
        offset: Pagination offset

    Returns:
        List of executions
    """
    return await service.list_all(
        user_id=user.id,
        workflow_id=workflow_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ExecutionRead, status_code=status.HTTP_201_CREATED)
async def create_execution(
    user: CurrentUser,
    service: ExecutionServiceDep,
    data: ExecutionCreate,
) -> ExecutionRead:
    """Create and start a new execution.

    The execution will be started immediately. Use the stream endpoint
    to get real-time updates.

    Args:
        user: Current authenticated user
        service: Execution service
        data: Execution creation data

    Returns:
        Created execution
    """
    try:
        logger.info(
            "execution_requested",
            user_id=user.id,
            workflow_id=data.workflow_id,
        )

        return await service.create_and_start(
            user_id=user.id,
            workflow_id=data.workflow_id,
            input_data=data.input_data,
        )
    except Exception as e:
        logger.error(
            "execution_creation_failed",
            user_id=user.id,
            workflow_id=data.workflow_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.get("/{execution_id}", response_model=ExecutionRead)
async def get_execution(
    execution_id: str,
    user: CurrentUser,
    service: ExecutionServiceDep,
) -> ExecutionRead:
    """Get an execution by ID.

    Args:
        execution_id: Execution identifier
        user: Current authenticated user
        service: Execution service

    Returns:
        Execution data
    """
    try:
        return await service.get(execution_id=execution_id, user_id=user.id)
    except ExecutionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ExecutionAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.get("/{execution_id}/stream")
async def stream_execution(
    execution_id: str,
    user: CurrentUser,
    service: ExecutionServiceDep,
) -> EventSourceResponse:
    """Stream execution events via SSE.

    Connect to this endpoint to receive real-time updates during
    workflow execution.

    Event types:
    - start: Execution has started
    - step: A node has completed
    - update: State update during execution
    - complete: Execution finished successfully
    - error: Execution failed

    Args:
        execution_id: Execution identifier
        user: Current authenticated user
        service: Execution service

    Returns:
        SSE event stream
    """
    # Verify access first
    try:
        await service.get(execution_id=execution_id, user_id=user.id)
    except ExecutionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ExecutionAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e

    async def event_generator():
        """Generate SSE events from execution."""
        try:
            async for event in service.execute(execution_id, user.id):
                yield {
                    "event": event.type,
                    "data": json.dumps(event.to_dict()),
                }
        except Exception as e:
            logger.exception(
                "stream_error",
                execution_id=execution_id,
                error=str(e),
            )
            yield {
                "event": "error",
                "data": json.dumps({
                    "type": "error",
                    "data": {"error": str(e)},
                }),
            }

    return EventSourceResponse(event_generator())


@router.post("/{execution_id}/cancel", response_model=ExecutionRead)
async def cancel_execution(
    execution_id: str,
    user: CurrentUser,
    service: ExecutionServiceDep,
) -> ExecutionRead:
    """Cancel a running execution.

    Args:
        execution_id: Execution identifier
        user: Current authenticated user
        service: Execution service

    Returns:
        Updated execution
    """
    try:
        return await service.cancel(execution_id=execution_id, user_id=user.id)
    except ExecutionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ExecutionAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except ExecutionServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.delete("/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_execution(
    execution_id: str,
    user: CurrentUser,
    service: ExecutionServiceDep,
) -> None:
    """Delete an execution record.

    Args:
        execution_id: Execution identifier
        user: Current authenticated user
        service: Execution service
    """
    try:
        await service.delete(execution_id=execution_id, user_id=user.id)
    except ExecutionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ExecutionAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


@router.post("/{execution_id}/retry", response_model=ExecutionRead, status_code=status.HTTP_201_CREATED)
async def retry_execution(
    execution_id: str,
    user: CurrentUser,
    service: ExecutionServiceDep,
) -> ExecutionRead:
    """Retry a failed execution.

    Creates a new execution with the same workflow and input data.

    Args:
        execution_id: Original execution identifier
        user: Current authenticated user
        service: Execution service

    Returns:
        New execution
    """
    try:
        # Get original execution
        original = await service.get(execution_id=execution_id, user_id=user.id)

        if original.status not in (ExecutionStatus.FAILED, ExecutionStatus.CANCELLED, ExecutionStatus.TIMEOUT):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot retry execution with status: {original.status.value}",
            )

        # Create new execution with same parameters
        return await service.create_and_start(
            user_id=user.id,
            workflow_id=original.workflow_id,
            input_data=original.input_data,
        )
    except ExecutionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ExecutionAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
