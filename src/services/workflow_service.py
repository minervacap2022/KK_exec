"""Workflow service.

Handles CRUD operations for workflows and NLP-based workflow building.
"""

import json
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.workflow_builder import BuildResult, WorkflowBuilder, WorkflowBuilderError
from src.models.workflow import (
    Workflow,
    WorkflowCreate,
    WorkflowGraph,
    WorkflowRead,
    WorkflowStatus,
    WorkflowUpdate,
)
from src.services.node_library import get_node_library

logger = structlog.get_logger()


class WorkflowServiceError(Exception):
    """Error in workflow service operations."""

    pass


class WorkflowNotFoundError(WorkflowServiceError):
    """Workflow not found."""

    pass


class WorkflowAccessDeniedError(WorkflowServiceError):
    """User doesn't have access to workflow."""

    pass


class WorkflowValidationError(WorkflowServiceError):
    """Workflow validation failed."""

    def __init__(self, message: str, errors: list[str]) -> None:
        super().__init__(message)
        self.errors = errors


class WorkflowService:
    """Service for managing workflows.

    Handles:
    - Creating workflows from graph JSON
    - Building workflows from NLP prompts
    - Reading and listing workflows
    - Updating workflow definitions
    - Deleting workflows
    - User-scoped access control

    Example usage:
        service = WorkflowService(session)

        # Create from graph
        workflow = await service.create(
            user_id="user-123",
            data=WorkflowCreate(
                name="My Workflow",
                graph={"nodes": [...], "edges": [...]}
            )
        )

        # Build from NLP
        result = await service.build_from_prompt(
            user_id="user-123",
            prompt="Send weather to Slack",
            available_credentials=["slack_oauth", "weather_api_key"]
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize workflow service.

        Args:
            session: Async database session
        """
        self._session = session
        self._node_library = get_node_library()

    async def create(
        self,
        user_id: str,
        data: WorkflowCreate,
    ) -> WorkflowRead:
        """Create a new workflow.

        Args:
            user_id: Owner user ID
            data: Workflow creation data

        Returns:
            Created workflow

        Raises:
            WorkflowValidationError: If graph is invalid
        """
        # Validate graph
        validation_errors = self._validate_graph(data.graph)
        if validation_errors:
            raise WorkflowValidationError(
                "Invalid workflow graph",
                errors=validation_errors,
            )

        # Create workflow entity
        workflow = Workflow(
            user_id=user_id,
            name=data.name,
            description=data.description,
            graph=data.graph.model_dump_json(),
            status=WorkflowStatus.DRAFT,
        )

        self._session.add(workflow)
        await self._session.commit()
        await self._session.refresh(workflow)

        logger.info(
            "workflow_created",
            workflow_id=workflow.id,
            user_id=user_id,
            node_count=len(data.graph.nodes),
        )

        return self._to_read(workflow)

    async def get(
        self,
        workflow_id: str,
        user_id: str,
    ) -> WorkflowRead:
        """Get a workflow.

        Args:
            workflow_id: Workflow ID
            user_id: Requesting user ID

        Returns:
            Workflow data

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
            WorkflowAccessDeniedError: If user doesn't own workflow
        """
        workflow = await self._get_and_verify(workflow_id, user_id)
        return self._to_read(workflow)

    async def list_all(
        self,
        user_id: str,
        status: WorkflowStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowRead]:
        """List user's workflows.

        Args:
            user_id: User ID
            status: Filter by status
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of workflows
        """
        query = (
            select(Workflow)
            .where(Workflow.user_id == user_id)
            .order_by(Workflow.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if status:
            query = query.where(Workflow.status == status)

        result = await self._session.execute(query)
        workflows = result.scalars().all()

        return [self._to_read(w) for w in workflows]

    async def update(
        self,
        workflow_id: str,
        user_id: str,
        data: WorkflowUpdate,
    ) -> WorkflowRead:
        """Update a workflow.

        Args:
            workflow_id: Workflow ID
            user_id: Requesting user ID
            data: Update data

        Returns:
            Updated workflow

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
            WorkflowAccessDeniedError: If user doesn't own workflow
            WorkflowValidationError: If graph is invalid
        """
        workflow = await self._get_and_verify(workflow_id, user_id)

        if data.name is not None:
            workflow.name = data.name

        if data.description is not None:
            workflow.description = data.description

        if data.graph is not None:
            validation_errors = self._validate_graph(data.graph)
            if validation_errors:
                raise WorkflowValidationError(
                    "Invalid workflow graph",
                    errors=validation_errors,
                )
            workflow.graph = data.graph.model_dump_json()
            workflow.version += 1

        if data.status is not None:
            workflow.status = data.status

        await self._session.commit()
        await self._session.refresh(workflow)

        logger.info(
            "workflow_updated",
            workflow_id=workflow_id,
            user_id=user_id,
            version=workflow.version,
        )

        return self._to_read(workflow)

    async def delete(
        self,
        workflow_id: str,
        user_id: str,
    ) -> None:
        """Delete a workflow.

        Args:
            workflow_id: Workflow ID
            user_id: Requesting user ID

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
            WorkflowAccessDeniedError: If user doesn't own workflow
        """
        workflow = await self._get_and_verify(workflow_id, user_id)

        await self._session.delete(workflow)
        await self._session.commit()

        logger.info(
            "workflow_deleted",
            workflow_id=workflow_id,
            user_id=user_id,
        )

    async def build_from_prompt(
        self,
        user_id: str,
        prompt: str,
        available_credentials: list[str] | None = None,
    ) -> WorkflowRead:
        """Build a workflow from a natural language prompt.

        Args:
            user_id: Owner user ID
            prompt: Natural language workflow description
            available_credentials: User's available credential types

        Returns:
            Created workflow with generated graph

        Raises:
            WorkflowServiceError: If building fails
        """
        try:
            # Get node catalog
            nodes = self._node_library.get_all_nodes()

            # Build workflow
            builder = WorkflowBuilder(node_catalog=nodes)
            result = await builder.build(
                prompt=prompt,
                available_credentials=available_credentials,
            )

            # Create workflow from result
            workflow = Workflow(
                user_id=user_id,
                name=result.name,
                description=result.description,
                graph=result.workflow_graph.model_dump_json(),
                status=WorkflowStatus.DRAFT,
            )

            self._session.add(workflow)
            await self._session.commit()
            await self._session.refresh(workflow)

            logger.info(
                "workflow_built_from_prompt",
                workflow_id=workflow.id,
                user_id=user_id,
                prompt_length=len(prompt),
                node_count=len(result.workflow_graph.nodes),
                warning_count=len(result.warnings),
            )

            return self._to_read(workflow)

        except WorkflowBuilderError as e:
            logger.error(
                "workflow_build_failed",
                user_id=user_id,
                error=str(e),
            )
            raise WorkflowServiceError(f"Failed to build workflow: {str(e)}") from e

    async def activate(
        self,
        workflow_id: str,
        user_id: str,
    ) -> WorkflowRead:
        """Activate a workflow.

        Args:
            workflow_id: Workflow ID
            user_id: Requesting user ID

        Returns:
            Updated workflow
        """
        return await self.update(
            workflow_id=workflow_id,
            user_id=user_id,
            data=WorkflowUpdate(status=WorkflowStatus.ACTIVE),
        )

    async def archive(
        self,
        workflow_id: str,
        user_id: str,
    ) -> WorkflowRead:
        """Archive a workflow.

        Args:
            workflow_id: Workflow ID
            user_id: Requesting user ID

        Returns:
            Updated workflow
        """
        return await self.update(
            workflow_id=workflow_id,
            user_id=user_id,
            data=WorkflowUpdate(status=WorkflowStatus.ARCHIVED),
        )

    async def duplicate(
        self,
        workflow_id: str,
        user_id: str,
        new_name: str | None = None,
    ) -> WorkflowRead:
        """Duplicate a workflow.

        Args:
            workflow_id: Source workflow ID
            user_id: Requesting user ID
            new_name: Name for the copy (defaults to "Copy of ...")

        Returns:
            New workflow copy
        """
        source = await self._get_and_verify(workflow_id, user_id)
        source_graph = WorkflowGraph.model_validate_json(source.graph)

        name = new_name or f"Copy of {source.name}"

        return await self.create(
            user_id=user_id,
            data=WorkflowCreate(
                name=name,
                description=source.description,
                graph=source_graph,
            ),
        )

    async def _get_and_verify(
        self,
        workflow_id: str,
        user_id: str,
    ) -> Workflow:
        """Get workflow and verify ownership.

        Args:
            workflow_id: Workflow ID
            user_id: Expected owner ID

        Returns:
            Workflow entity

        Raises:
            WorkflowNotFoundError: If not found
            WorkflowAccessDeniedError: If wrong owner
        """
        query = select(Workflow).where(Workflow.id == workflow_id)
        result = await self._session.execute(query)
        workflow = result.scalar_one_or_none()

        if workflow is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found")

        if workflow.user_id != user_id:
            logger.warning(
                "workflow_access_denied",
                workflow_id=workflow_id,
                requested_by=user_id,
                owner=workflow.user_id,
            )
            raise WorkflowAccessDeniedError("Access denied to workflow")

        return workflow

    def _validate_graph(self, graph: WorkflowGraph) -> list[str]:
        """Validate a workflow graph.

        Args:
            graph: Graph to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check for duplicate node IDs
        node_ids = [n.id for n in graph.nodes]
        if len(node_ids) != len(set(node_ids)):
            errors.append("Duplicate node IDs detected")

        # Check node types exist
        for node in graph.nodes:
            if self._node_library.get(node.type) is None:
                errors.append(f"Unknown node type: {node.type}")

        # Check edge references
        node_id_set = set(node_ids)
        for edge in graph.edges:
            if edge.source not in node_id_set:
                errors.append(f"Edge references unknown source node: {edge.source}")
            if edge.target not in node_id_set:
                errors.append(f"Edge references unknown target node: {edge.target}")

        # Check for self-loops
        for edge in graph.edges:
            if edge.source == edge.target:
                errors.append(f"Self-loop detected on node: {edge.source}")

        return errors

    def _to_read(self, workflow: Workflow) -> WorkflowRead:
        """Convert workflow entity to read schema."""
        return WorkflowRead(
            id=workflow.id,
            user_id=workflow.user_id,
            name=workflow.name,
            description=workflow.description,
            graph=WorkflowGraph.model_validate_json(workflow.graph),
            status=workflow.status,
            version=workflow.version,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )
