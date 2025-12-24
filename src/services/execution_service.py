"""Execution service.

Handles workflow execution lifecycle and state management.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from src.core.execution_engine import (
    ExecutionError,
    ExecutionEvent,
    WorkflowExecutionEngine,
)
from src.models.credential import Credential
from src.models.execution import (
    Execution,
    ExecutionCreate,
    ExecutionRead,
    ExecutionStatus,
)
from src.models.workflow import Workflow
from src.services.credential_service import CredentialService
from src.services.workflow_service import WorkflowNotFoundError, WorkflowService

logger = structlog.get_logger()

# Will be set by init_execution_service
_session_maker: sessionmaker | None = None


def init_execution_service(session_maker: sessionmaker) -> None:
    """Initialize execution service with session maker.

    Args:
        session_maker: SQLAlchemy async session maker
    """
    global _session_maker
    _session_maker = session_maker
    logger.info("execution_service_initialized")


def utc_now() -> datetime:
    """Get current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class ExecutionServiceError(Exception):
    """Error in execution service operations."""

    pass


class ExecutionNotFoundError(ExecutionServiceError):
    """Execution not found."""

    pass


class ExecutionAccessDeniedError(ExecutionServiceError):
    """User doesn't have access to execution."""

    pass


class ExecutionService:
    """Service for managing workflow executions.

    Handles:
    - Creating and starting executions
    - Tracking execution status
    - Streaming execution events
    - Managing execution history

    Example usage:
        service = ExecutionService(session, workflow_service, credential_service)

        # Start execution
        execution = await service.create_and_start(
            user_id="user-123",
            workflow_id="workflow-456",
            input_data={"message": "Hello"}
        )

        # Stream events
        async for event in service.stream(execution.id, user_id):
            print(event.type, event.data)
    """

    def __init__(
        self,
        session: AsyncSession,
        workflow_service: WorkflowService,
        credential_service: CredentialService,
    ) -> None:
        """Initialize execution service.

        Args:
            session: Async database session
            workflow_service: Workflow service instance
            credential_service: Credential service instance
        """
        self._session = session
        self._workflow_service = workflow_service
        self._credential_service = credential_service
        self._engine = WorkflowExecutionEngine()

    async def create(
        self,
        user_id: str,
        data: ExecutionCreate,
    ) -> ExecutionRead:
        """Create a new execution record.

        Args:
            user_id: User triggering execution
            data: Execution creation data

        Returns:
            Created execution

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        # Verify workflow exists and user has access
        await self._workflow_service.get(data.workflow_id, user_id)

        # Create execution
        execution = Execution(
            workflow_id=data.workflow_id,
            user_id=user_id,
            status=ExecutionStatus.PENDING,
        )

        if data.input_data:
            execution.set_input_data(data.input_data)

        self._session.add(execution)
        await self._session.commit()
        await self._session.refresh(execution)

        logger.info(
            "execution_created",
            execution_id=execution.id,
            workflow_id=data.workflow_id,
            user_id=user_id,
        )

        return self._to_read(execution)

    async def create_and_start(
        self,
        user_id: str,
        workflow_id: str,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionRead:
        """Create and immediately start an execution.

        Args:
            user_id: User triggering execution
            workflow_id: Workflow to execute
            input_data: Input data for workflow

        Returns:
            Execution record (status will be RUNNING)
        """
        # Create execution
        execution = await self.create(
            user_id=user_id,
            data=ExecutionCreate(
                workflow_id=workflow_id,
                input_data=input_data,
            ),
        )

        # Mark as running
        await self._update_status(execution.id, ExecutionStatus.RUNNING)

        # Execute synchronously (MCP client doesn't work well with asyncio.create_task)
        logger.info(
            "execution_starting",
            execution_id=execution.id,
            user_id=user_id,
        )

        try:
            async for event in self.execute(execution.id, user_id):
                logger.debug(
                    "execution_event",
                    execution_id=execution.id,
                    event_type=event.type,
                )
        except Exception as e:
            logger.exception(
                "execution_failed",
                execution_id=execution.id,
                error=str(e),
            )

        return await self.get(execution.id, user_id)

    async def get(
        self,
        execution_id: str,
        user_id: str,
    ) -> ExecutionRead:
        """Get an execution.

        Args:
            execution_id: Execution ID
            user_id: Requesting user ID

        Returns:
            Execution data

        Raises:
            ExecutionNotFoundError: If execution doesn't exist
            ExecutionAccessDeniedError: If user doesn't own execution
        """
        execution = await self._get_and_verify(execution_id, user_id)
        return self._to_read(execution)

    async def list_all(
        self,
        user_id: str,
        workflow_id: str | None = None,
        status: ExecutionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionRead]:
        """List user's executions.

        Args:
            user_id: User ID
            workflow_id: Filter by workflow
            status: Filter by status
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of executions
        """
        query = (
            select(Execution)
            .where(Execution.user_id == user_id)
            .order_by(Execution.started_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if workflow_id:
            query = query.where(Execution.workflow_id == workflow_id)
        if status:
            query = query.where(Execution.status == status)

        result = await self._session.execute(query)
        executions = result.scalars().all()

        return [self._to_read(e) for e in executions]

    async def execute(
        self,
        execution_id: str,
        user_id: str,
    ) -> AsyncGenerator[ExecutionEvent, None]:
        """Execute a workflow and stream events.

        Args:
            execution_id: Execution ID
            user_id: Requesting user ID

        Yields:
            Execution events

        Raises:
            ExecutionNotFoundError: If execution doesn't exist
            ExecutionAccessDeniedError: If user doesn't own execution
        """
        execution = await self._get_and_verify(execution_id, user_id)

        if execution.status not in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
            raise ExecutionServiceError(
                f"Cannot execute: status is {execution.status.value}"
            )

        # Get workflow
        workflow_query = select(Workflow).where(Workflow.id == execution.workflow_id)
        result = await self._session.execute(workflow_query)
        workflow = result.scalar_one()

        # Get user credentials
        credentials = await self._credential_service.list_all_decrypted(user_id)

        # Update status to running
        execution.mark_running()
        await self._session.commit()

        try:
            # Execute workflow
            input_data = execution.get_input_data() or {}

            async for event in self._engine.execute(
                workflow=workflow,
                input_data=input_data,
                user_credentials=credentials,
                stream=True,
            ):
                # Update execution state based on event
                if event.type == "step":
                    execution.steps_completed = event.step_number or 0
                    execution.current_node_id = event.node_id
                    execution.trace_id = event.trace_id
                    await self._session.commit()

                elif event.type == "complete":
                    execution.mark_completed(event.data.get("output", {}))
                    await self._session.commit()

                elif event.type == "error":
                    execution.mark_failed(
                        error=event.data.get("error", "Unknown error"),
                        error_code=event.data.get("error_type"),
                    )
                    await self._session.commit()

                yield event

        except ExecutionError as e:
            execution.mark_failed(str(e), e.error_code)
            await self._session.commit()

            yield ExecutionEvent(
                type="error",
                trace_id=execution.trace_id,
                data={"error": str(e), "error_code": e.error_code},
            )

        except Exception as e:
            execution.mark_failed(str(e), "UNEXPECTED_ERROR")
            await self._session.commit()

            logger.exception(
                "execution_failed_unexpected",
                execution_id=execution_id,
            )

            yield ExecutionEvent(
                type="error",
                trace_id=execution.trace_id,
                data={"error": str(e), "error_type": type(e).__name__},
            )

    async def cancel(
        self,
        execution_id: str,
        user_id: str,
    ) -> ExecutionRead:
        """Cancel a running execution.

        Args:
            execution_id: Execution ID
            user_id: Requesting user ID

        Returns:
            Updated execution

        Raises:
            ExecutionNotFoundError: If execution doesn't exist
            ExecutionAccessDeniedError: If user doesn't own execution
            ExecutionServiceError: If execution cannot be cancelled
        """
        execution = await self._get_and_verify(execution_id, user_id)

        if execution.status not in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
            raise ExecutionServiceError(
                f"Cannot cancel: status is {execution.status.value}"
            )

        execution.mark_cancelled()
        await self._session.commit()
        await self._session.refresh(execution)

        logger.info(
            "execution_cancelled",
            execution_id=execution_id,
            user_id=user_id,
        )

        return self._to_read(execution)

    async def delete(
        self,
        execution_id: str,
        user_id: str,
    ) -> None:
        """Delete an execution record.

        Args:
            execution_id: Execution ID
            user_id: Requesting user ID

        Raises:
            ExecutionNotFoundError: If execution doesn't exist
            ExecutionAccessDeniedError: If user doesn't own execution
        """
        execution = await self._get_and_verify(execution_id, user_id)

        await self._session.delete(execution)
        await self._session.commit()

        logger.info(
            "execution_deleted",
            execution_id=execution_id,
            user_id=user_id,
        )

    async def _get_and_verify(
        self,
        execution_id: str,
        user_id: str,
    ) -> Execution:
        """Get execution and verify ownership.

        Args:
            execution_id: Execution ID
            user_id: Expected owner ID

        Returns:
            Execution entity

        Raises:
            ExecutionNotFoundError: If not found
            ExecutionAccessDeniedError: If wrong owner
        """
        query = select(Execution).where(Execution.id == execution_id)
        result = await self._session.execute(query)
        execution = result.scalar_one_or_none()

        if execution is None:
            raise ExecutionNotFoundError(f"Execution '{execution_id}' not found")

        if execution.user_id != user_id:
            logger.warning(
                "execution_access_denied",
                execution_id=execution_id,
                requested_by=user_id,
                owner=execution.user_id,
            )
            raise ExecutionAccessDeniedError("Access denied to execution")

        return execution

    async def _update_status(
        self,
        execution_id: str,
        status: ExecutionStatus,
    ) -> None:
        """Update execution status."""
        query = select(Execution).where(Execution.id == execution_id)
        result = await self._session.execute(query)
        execution = result.scalar_one()
        execution.status = status
        await self._session.commit()

    async def _run_execution_background(
        self,
        execution_id: str,
        user_id: str,
    ) -> None:
        """Run execution in background with its own database session.

        Creates a new session to avoid sharing state with the request session.
        All state updates are handled inside execute() method.
        """
        if _session_maker is None:
            logger.error(
                "background_execution_no_session_maker",
                execution_id=execution_id,
            )
            return

        # Create new session for background execution
        async with _session_maker() as session:
            try:
                # Create service instances with new session
                workflow_service = WorkflowService(session)
                credential_service = CredentialService(session)
                execution_service = ExecutionService(
                    session,
                    workflow_service,
                    credential_service,
                )

                # Execute workflow
                async for event in execution_service.execute(execution_id, user_id):
                    # Events are already being processed by execute()
                    # Just consume them to drive the execution forward
                    logger.debug(
                        "execution_event",
                        execution_id=execution_id,
                        event_type=event.type,
                    )

            except Exception as e:
                logger.exception(
                    "background_execution_failed",
                    execution_id=execution_id,
                    error=str(e),
                )

    def _to_read(self, execution: Execution) -> ExecutionRead:
        """Convert execution entity to read schema."""
        return ExecutionRead(
            id=execution.id,
            workflow_id=execution.workflow_id,
            user_id=execution.user_id,
            status=execution.status,
            input_data=execution.get_input_data(),
            output_data=execution.get_output_data(),
            error=execution.error,
            error_code=execution.error_code,
            steps_completed=execution.steps_completed,
            current_node_id=execution.current_node_id,
            trace_id=execution.trace_id,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            duration_ms=execution.duration_ms,
        )
