"""JSON transformer node.

Transforms JSON data using JSONPath expressions.
"""

import json
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
class JsonTransformerInput:
    """Input for JSON transformer node."""

    data: dict[str, Any] | list[Any]
    path: str


@dataclass
class JsonTransformerOutput:
    """Output from JSON transformer node."""

    result: Any
    matched: bool


def simple_jsonpath(data: Any, path: str) -> tuple[Any, bool]:
    """Simple JSONPath-like expression evaluator.

    Supports:
    - $.key - Access object key
    - $[0] - Access array index
    - $.key1.key2 - Nested access
    - $.key[0] - Mixed access
    - $ - Root element

    Args:
        data: JSON data
        path: Path expression

    Returns:
        Tuple of (result, matched)
    """
    if not path.startswith("$"):
        raise ValueError("Path must start with '$'")

    # Root reference
    if path == "$":
        return data, True

    # Remove $ prefix
    remaining = path[1:]
    current = data

    while remaining:
        # Handle dot notation
        if remaining.startswith("."):
            remaining = remaining[1:]
            # Find next separator
            end = len(remaining)
            for i, c in enumerate(remaining):
                if c in ".[":
                    end = i
                    break

            key = remaining[:end]
            remaining = remaining[end:]

            if not isinstance(current, dict):
                return None, False
            if key not in current:
                return None, False

            current = current[key]

        # Handle bracket notation
        elif remaining.startswith("["):
            end = remaining.find("]")
            if end == -1:
                raise ValueError("Unclosed bracket in path")

            index_str = remaining[1:end]
            remaining = remaining[end + 1:]

            try:
                index = int(index_str)
            except ValueError:
                # Try as string key (quoted)
                if index_str.startswith("'") and index_str.endswith("'"):
                    key = index_str[1:-1]
                    if not isinstance(current, dict) or key not in current:
                        return None, False
                    current = current[key]
                    continue
                raise ValueError(f"Invalid index: {index_str}")

            if not isinstance(current, (list, tuple)):
                return None, False
            if index < 0 or index >= len(current):
                return None, False

            current = current[index]

        else:
            raise ValueError(f"Invalid path syntax at: {remaining}")

    return current, True


class JsonTransformerNode(BaseNode[JsonTransformerInput, JsonTransformerOutput]):
    """JSON transformer node using JSONPath-like expressions.

    Supports basic JSONPath syntax:
    - $.key - Access object key
    - $[0] - Access array index
    - $.key1.key2 - Nested access

    Example:
        result = await node.run(
            {
                "data": {"users": [{"name": "Alice"}, {"name": "Bob"}]},
                "path": "$.users[0].name"
            },
            context
        )
        # result = {"result": "Alice", "matched": true}
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="json_transformer",
            display_name="JSON Transformer",
            description="Extract data from JSON using path expressions",
            category=NodeCategory.TOOL,
            inputs=[
                NodeInput(
                    name="data",
                    display_name="JSON Data",
                    type=NodeInputType.JSON,
                    description="Input JSON data",
                    required=True,
                ),
                NodeInput(
                    name="path",
                    display_name="Path",
                    type=NodeInputType.STRING,
                    description="JSONPath expression (e.g., $.users[0].name)",
                    required=True,
                ),
            ],
            outputs=[
                NodeOutput(
                    name="result",
                    display_name="Result",
                    type=NodeOutputType.JSON,
                    description="Extracted data",
                ),
                NodeOutput(
                    name="matched",
                    display_name="Matched",
                    type=NodeOutputType.BOOLEAN,
                    description="Whether the path matched",
                ),
            ],
            tags=["json", "transform", "extract", "jsonpath"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> JsonTransformerInput:
        """Validate input data."""
        data = input_data.get("data")
        path = input_data.get("path")

        if data is None:
            raise NodeValidationError("Data is required", field="data")

        if not isinstance(data, (dict, list)):
            # Try to parse as JSON string
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError as e:
                    raise NodeValidationError(
                        f"Invalid JSON string: {str(e)}", field="data"
                    ) from e
            else:
                raise NodeValidationError(
                    "Data must be a JSON object or array", field="data"
                )

        if not path:
            raise NodeValidationError("Path is required", field="path")

        if not isinstance(path, str):
            raise NodeValidationError("Path must be a string", field="path")

        if not path.startswith("$"):
            raise NodeValidationError(
                "Path must start with '$'", field="path"
            )

        return JsonTransformerInput(data=data, path=path)

    async def execute(
        self,
        input_data: JsonTransformerInput,
        context: NodeContext,
    ) -> JsonTransformerOutput:
        """Execute the JSON transformation."""
        try:
            result, matched = simple_jsonpath(input_data.data, input_data.path)
            return JsonTransformerOutput(result=result, matched=matched)
        except ValueError as e:
            raise NodeExecutionError(
                message=str(e),
                node_name="json_transformer",
                error_code="INVALID_PATH",
            ) from e
