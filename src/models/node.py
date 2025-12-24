"""Node definition model.

Runtime model for workflow nodes (not persisted to database).
Defines the structure and metadata for available workflow nodes.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class NodeCategory(str, Enum):
    """Node category for organization and filtering."""

    TOOL = "tool"  # Built-in tools, no auth required
    API = "api"  # External APIs, API key required
    MCP = "mcp"  # MCP integrations, user-specific auth


class NodeInputType(str, Enum):
    """Supported input types for node inputs."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"
    ARRAY = "array"
    FILE = "file"
    ANY = "any"


class NodeOutputType(str, Enum):
    """Supported output types for node outputs."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"
    ARRAY = "array"
    FILE = "file"
    ANY = "any"


@dataclass
class NodeInput:
    """Definition of a node input parameter."""

    name: str
    display_name: str
    type: NodeInputType
    description: str = ""
    required: bool = True
    default: Any = None
    options: list[str] | None = None  # For enum-like inputs


@dataclass
class NodeOutput:
    """Definition of a node output parameter."""

    name: str
    display_name: str
    type: NodeOutputType
    description: str = ""


@dataclass
class NodeDefinition:
    """Complete node definition with metadata and schema.

    This is a runtime model used for node discovery and catalog.
    Not persisted to database - loaded from node implementations.
    """

    name: str  # Unique identifier (e.g., 'openai_chat')
    display_name: str  # Human-readable name (e.g., 'OpenAI Chat')
    description: str
    category: NodeCategory
    inputs: list[NodeInput] = field(default_factory=list)
    outputs: list[NodeOutput] = field(default_factory=list)
    credential_type: str | None = None  # Required credential type
    mcp_server_id: str | None = None  # Associated MCP server
    icon: str | None = None  # Icon identifier or URL
    version: str = "1.0.0"
    deprecated: bool = False
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category.value,
            "inputs": [
                {
                    "name": inp.name,
                    "display_name": inp.display_name,
                    "type": inp.type.value,
                    "description": inp.description,
                    "required": inp.required,
                    "default": inp.default,
                    "options": inp.options,
                }
                for inp in self.inputs
            ],
            "outputs": [
                {
                    "name": out.name,
                    "display_name": out.display_name,
                    "type": out.type.value,
                    "description": out.description,
                }
                for out in self.outputs
            ],
            "credential_type": self.credential_type,
            "mcp_server_id": self.mcp_server_id,
            "icon": self.icon,
            "version": self.version,
            "deprecated": self.deprecated,
            "tags": self.tags,
        }


@dataclass
class NodeInstance:
    """Instance of a node in a workflow graph.

    Represents a configured node with its specific settings.
    """

    id: str  # Unique instance ID within the workflow
    node_type: str  # Reference to NodeDefinition.name
    config: dict[str, Any] = field(default_factory=dict)
    position: dict[str, int] = field(default_factory=lambda: {"x": 0, "y": 0})

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for graph storage."""
        return {
            "id": self.id,
            "type": self.node_type,
            "config": self.config,
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeInstance":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            node_type=data["type"],
            config=data.get("config", {}),
            position=data.get("position", {"x": 0, "y": 0}),
        )


@dataclass
class GraphEdge:
    """Edge connecting two nodes in a workflow graph."""

    source: str  # Source node ID
    target: str  # Target node ID
    source_handle: str = "output"  # Output name on source
    target_handle: str = "input"  # Input name on target

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for graph storage."""
        return {
            "source": self.source,
            "target": self.target,
            "sourceHandle": self.source_handle,
            "targetHandle": self.target_handle,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "GraphEdge":
        """Create from dictionary."""
        return cls(
            source=data["source"],
            target=data["target"],
            source_handle=data.get("sourceHandle", "output"),
            target_handle=data.get("targetHandle", "input"),
        )
