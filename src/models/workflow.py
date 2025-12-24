"""Workflow entity model.

Defines the Workflow table for storing workflow definitions.
Workflows are stored as JSON graphs with nodes and edges.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import field_validator
from sqlmodel import Column, Field, Relationship, SQLModel, Text
import json

if TYPE_CHECKING:
    from src.models.execution import Execution
    from src.models.user import User


def utc_now() -> datetime:
    """Get current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class WorkflowStatus(str, Enum):
    """Workflow lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class WorkflowBase(SQLModel):
    """Base workflow fields shared across models."""

    name: str = Field(
        max_length=255,
        min_length=1,
        description="Workflow name",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Workflow description",
    )


class Workflow(WorkflowBase, table=True):
    """Workflow database entity.

    Stores workflow definitions as JSON graphs.
    Graph schema:
    {
        "version": "1.0",
        "nodes": [{"id": str, "type": str, "config": dict, "position": {"x": int, "y": int}}],
        "edges": [{"source": str, "target": str, "sourceHandle": str, "targetHandle": str}],
        "config": {}
    }
    """

    __tablename__ = "workflow"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique workflow identifier (UUID)",
    )
    user_id: str = Field(
        foreign_key="user.id",
        index=True,
        description="Owner user ID",
    )
    graph: str = Field(
        sa_column=Column(Text, nullable=False),
        description="JSON workflow graph definition",
    )
    status: WorkflowStatus = Field(
        default=WorkflowStatus.DRAFT,
        description="Workflow lifecycle status",
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Workflow version number",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Creation timestamp (UTC)",
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column_kwargs={"onupdate": utc_now},
        description="Last update timestamp (UTC)",
    )

    # Relationships
    user: "User" = Relationship(back_populates="workflows")
    executions: list["Execution"] = Relationship(back_populates="workflow")

    def get_graph(self) -> dict[str, Any]:
        """Parse and return the workflow graph as a dictionary."""
        return json.loads(self.graph)

    def set_graph(self, graph_dict: dict[str, Any]) -> None:
        """Set the workflow graph from a dictionary."""
        self.graph = json.dumps(graph_dict)


class WorkflowGraphNode(SQLModel):
    """Schema for a node in the workflow graph."""

    id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, int] = Field(default_factory=lambda: {"x": 0, "y": 0})


class WorkflowGraphEdge(SQLModel):
    """Schema for an edge in the workflow graph."""

    source: str
    target: str
    sourceHandle: str = "output"
    targetHandle: str = "input"


class WorkflowGraph(SQLModel):
    """Schema for the complete workflow graph."""

    version: str = "1.0"
    nodes: list[WorkflowGraphNode] = Field(default_factory=list)
    edges: list[WorkflowGraphEdge] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(WorkflowBase):
    """Schema for creating a new workflow."""

    graph: WorkflowGraph

    @field_validator("graph", mode="before")
    @classmethod
    def validate_graph(cls, v: Any) -> WorkflowGraph:
        """Validate and parse graph input."""
        if isinstance(v, dict):
            return WorkflowGraph(**v)
        return v


class WorkflowUpdate(SQLModel):
    """Schema for updating a workflow."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    graph: WorkflowGraph | None = None
    status: WorkflowStatus | None = None


class WorkflowRead(WorkflowBase):
    """Schema for reading workflow data."""

    id: str
    user_id: str
    graph: WorkflowGraph
    status: WorkflowStatus
    version: int
    created_at: datetime
    updated_at: datetime

    @field_validator("graph", mode="before")
    @classmethod
    def parse_graph(cls, v: Any) -> WorkflowGraph:
        """Parse graph from JSON string or dict."""
        if isinstance(v, str):
            return WorkflowGraph(**json.loads(v))
        if isinstance(v, dict):
            return WorkflowGraph(**v)
        return v


class WorkflowBuildRequest(SQLModel):
    """Schema for NLP-based workflow building request."""

    prompt: str = Field(
        min_length=10,
        max_length=5000,
        description="Natural language description of the workflow",
    )
    available_credentials: list[str] | None = Field(
        default=None,
        description="List of available credential types for the user",
    )


class WorkflowBuildResponse(SQLModel):
    """Schema for NLP-based workflow building response."""

    workflow: WorkflowRead
    explanation: str = Field(
        description="Explanation of the generated workflow",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Any warnings about the generated workflow",
    )
