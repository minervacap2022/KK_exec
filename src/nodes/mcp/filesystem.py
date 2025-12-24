"""Filesystem MCP node.

Interacts with filesystem via MCP server.
"""

from dataclasses import dataclass
from typing import Any

from src.models.node import (
    NodeCategory,
    NodeDefinition,
    NodeInput,
    NodeInputType,
    NodeOutput,
    NodeOutputType,
)
from src.nodes.base import BaseNode, NodeContext, NodeExecutionError, NodeValidationError


@dataclass
class FileReadInput:
    """Input for file read."""

    path: str


@dataclass
class FileReadOutput:
    """Output from file read."""

    content: str
    path: str
    size: int


class FilesystemMCPNode(BaseNode[FileReadInput, FileReadOutput]):
    """Filesystem MCP node for reading files.

    Uses MCP server for filesystem operations.
    No credentials required (local filesystem access).

    Example:
        result = await node.run(
            {"path": "/path/to/file.txt"},
            context
        )
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="filesystem_read",
            display_name="Read File",
            description="Read contents of a file",
            category=NodeCategory.MCP,
            mcp_server_id="filesystem",
            inputs=[
                NodeInput(
                    name="path",
                    display_name="File Path",
                    type=NodeInputType.STRING,
                    description="Path to the file to read",
                    required=True,
                ),
            ],
            outputs=[
                NodeOutput(
                    name="content",
                    display_name="Content",
                    type=NodeOutputType.STRING,
                    description="File content",
                ),
                NodeOutput(
                    name="path",
                    display_name="Path",
                    type=NodeOutputType.STRING,
                    description="Absolute path to file",
                ),
                NodeOutput(
                    name="size",
                    display_name="Size",
                    type=NodeOutputType.NUMBER,
                    description="File size in bytes",
                ),
            ],
            tags=["filesystem", "file", "read"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> FileReadInput:
        """Validate input data."""
        path = input_data.get("path")

        if not path:
            raise NodeValidationError("Path is required", field="path")

        if not isinstance(path, str):
            raise NodeValidationError("Path must be a string", field="path")

        # Basic path validation
        if ".." in path:
            raise NodeValidationError(
                "Path traversal not allowed", field="path"
            )

        return FileReadInput(path=path)

    async def execute(
        self,
        input_data: FileReadInput,
        context: NodeContext,
    ) -> FileReadOutput:
        """Execute file read via MCP."""
        # TODO: Implement actual MCP call
        # Placeholder
        return FileReadOutput(
            content="File content placeholder",
            path=input_data.path,
            size=24,
        )
