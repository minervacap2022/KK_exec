"""Execution entity model.

Defines the Execution table for tracking workflow executions.
Includes status, input/output data, timing, and error information.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4
import json

from sqlmodel import Column, Field, Relationship, SQLModel, Text

if TYPE_CHECKING:
    from src.models.user import User
    from src.models.workflow import Workflow


def utc_now() -> datetime:
    """Get current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class ExecutionStatus(str, Enum):
    """Execution lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class Execution(SQLModel, table=True):
    """Execution database entity.

    Tracks the full lifecycle of a workflow execution including:
    - Status transitions
    - Input/output data
    - Error information
    - Timing metrics

    Input and output data are stored as JSON strings.
    """

    __tablename__ = "execution"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique execution identifier (UUID)",
    )
    workflow_id: str = Field(
        foreign_key="workflow.id",
        index=True,
        description="Associated workflow ID",
    )
    user_id: str = Field(
        foreign_key="user.id",
        index=True,
        description="User who triggered the execution",
    )
    status: ExecutionStatus = Field(
        default=ExecutionStatus.PENDING,
        index=True,
        description="Current execution status",
    )
    input_data: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="JSON input data for the workflow",
    )
    output_data: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="JSON output data from the workflow",
    )
    error: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Error message if execution failed",
    )
    error_code: str | None = Field(
        default=None,
        max_length=100,
        description="Error code for programmatic error handling",
    )
    steps_completed: int = Field(
        default=0,
        ge=0,
        description="Number of steps completed",
    )
    current_node_id: str | None = Field(
        default=None,
        max_length=100,
        description="ID of the currently executing node",
    )
    trace_id: str | None = Field(
        default=None,
        max_length=100,
        description="OpenTelemetry trace ID for distributed tracing",
    )
    started_at: datetime = Field(
        default_factory=utc_now,
        description="Execution start timestamp (UTC)",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Execution completion timestamp (UTC)",
    )

    # Relationships
    workflow: "Workflow" = Relationship(back_populates="executions")
    user: "User" = Relationship(back_populates="executions")

    def get_input_data(self) -> dict[str, Any] | None:
        """Parse and return input data as a dictionary."""
        if self.input_data is None:
            return None
        return json.loads(self.input_data)

    def set_input_data(self, data: dict[str, Any]) -> None:
        """Set input data from a dictionary."""
        self.input_data = json.dumps(data)

    def get_output_data(self) -> dict[str, Any] | None:
        """Parse and return output data as a dictionary."""
        if self.output_data is None:
            return None
        return json.loads(self.output_data)

    def set_output_data(self, data: dict[str, Any]) -> None:
        """Set output data from a dictionary."""
        self.output_data = json.dumps(data)

    @property
    def duration_ms(self) -> int | None:
        """Calculate execution duration in milliseconds."""
        if self.completed_at is None:
            return None
        delta = self.completed_at - self.started_at
        return int(delta.total_seconds() * 1000)

    def mark_running(self) -> None:
        """Mark execution as running."""
        self.status = ExecutionStatus.RUNNING

    def mark_completed(self, output_data: dict[str, Any]) -> None:
        """Mark execution as completed with output data."""
        self.status = ExecutionStatus.COMPLETED
        self.set_output_data(output_data)
        self.completed_at = utc_now()

    def mark_failed(self, error: str, error_code: str | None = None) -> None:
        """Mark execution as failed with error information."""
        self.status = ExecutionStatus.FAILED
        self.error = error
        self.error_code = error_code
        self.completed_at = utc_now()

    def mark_cancelled(self) -> None:
        """Mark execution as cancelled."""
        self.status = ExecutionStatus.CANCELLED
        self.completed_at = utc_now()

    def mark_timeout(self) -> None:
        """Mark execution as timed out."""
        self.status = ExecutionStatus.TIMEOUT
        self.error = "Execution exceeded maximum allowed time"
        self.error_code = "EXECUTION_TIMEOUT"
        self.completed_at = utc_now()


class ExecutionCreate(SQLModel):
    """Schema for creating a new execution."""

    workflow_id: str
    input_data: dict[str, Any] | None = None


class ExecutionRead(SQLModel):
    """Schema for reading execution data."""

    id: str
    workflow_id: str
    user_id: str
    status: ExecutionStatus
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    steps_completed: int
    current_node_id: str | None = None
    trace_id: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None


class ExecutionEvent(SQLModel):
    """Schema for execution streaming events."""

    type: str = Field(
        description="Event type: 'update', 'complete', 'error', 'step'",
    )
    timestamp: datetime = Field(
        default_factory=utc_now,
        description="Event timestamp (UTC)",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload",
    )
    trace_id: str | None = None
    node_id: str | None = None
    step_number: int | None = None


class ExecutionStepEvent(SQLModel):
    """Schema for step-level execution events."""

    node_id: str
    node_type: str
    status: str  # 'started', 'completed', 'failed'
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None
    timestamp: datetime = Field(default_factory=utc_now)
