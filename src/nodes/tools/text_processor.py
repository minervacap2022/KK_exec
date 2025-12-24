"""Text processor node.

Performs text transformations.
"""

from dataclasses import dataclass
from typing import Any, Literal

from src.models.node import (
    NodeCategory,
    NodeDefinition,
    NodeInput,
    NodeInputType,
    NodeOutput,
    NodeOutputType,
)
from src.nodes.base import BaseNode, NodeContext, NodeExecutionError, NodeValidationError


Operation = Literal["uppercase", "lowercase", "trim", "reverse", "capitalize", "title"]


@dataclass
class TextProcessorInput:
    """Input for text processor node."""

    text: str
    operation: Operation


@dataclass
class TextProcessorOutput:
    """Output from text processor node."""

    result: str
    original_length: int
    result_length: int


class TextProcessorNode(BaseNode[TextProcessorInput, TextProcessorOutput]):
    """Text processor node for string transformations.

    Supported operations:
    - uppercase: Convert to uppercase
    - lowercase: Convert to lowercase
    - trim: Remove leading/trailing whitespace
    - reverse: Reverse the string
    - capitalize: Capitalize first character
    - title: Title case

    Example:
        result = await node.run(
            {"text": "hello world", "operation": "uppercase"},
            context
        )
        # result = {"result": "HELLO WORLD", ...}
    """

    OPERATIONS = {
        "uppercase": lambda s: s.upper(),
        "lowercase": lambda s: s.lower(),
        "trim": lambda s: s.strip(),
        "reverse": lambda s: s[::-1],
        "capitalize": lambda s: s.capitalize(),
        "title": lambda s: s.title(),
    }

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="text_processor",
            display_name="Text Processor",
            description="Transform text with various operations",
            category=NodeCategory.TOOL,
            inputs=[
                NodeInput(
                    name="text",
                    display_name="Text",
                    type=NodeInputType.STRING,
                    description="Input text to process",
                    required=True,
                ),
                NodeInput(
                    name="operation",
                    display_name="Operation",
                    type=NodeInputType.STRING,
                    description="Processing operation",
                    required=True,
                    options=list(self.OPERATIONS.keys()),
                ),
            ],
            outputs=[
                NodeOutput(
                    name="result",
                    display_name="Result",
                    type=NodeOutputType.STRING,
                    description="Processed text",
                ),
                NodeOutput(
                    name="original_length",
                    display_name="Original Length",
                    type=NodeOutputType.NUMBER,
                    description="Length of original text",
                ),
                NodeOutput(
                    name="result_length",
                    display_name="Result Length",
                    type=NodeOutputType.NUMBER,
                    description="Length of result",
                ),
            ],
            tags=["text", "string", "transform"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> TextProcessorInput:
        """Validate input data."""
        text = input_data.get("text")
        operation = input_data.get("operation")

        if text is None:
            raise NodeValidationError("Text is required", field="text")

        if not isinstance(text, str):
            raise NodeValidationError("Text must be a string", field="text")

        if not operation:
            raise NodeValidationError("Operation is required", field="operation")

        if operation not in self.OPERATIONS:
            raise NodeValidationError(
                f"Invalid operation: {operation}. Must be one of: {list(self.OPERATIONS.keys())}",
                field="operation",
            )

        return TextProcessorInput(text=text, operation=operation)

    async def execute(
        self,
        input_data: TextProcessorInput,
        context: NodeContext,
    ) -> TextProcessorOutput:
        """Execute the text transformation."""
        op_func = self.OPERATIONS[input_data.operation]
        result = op_func(input_data.text)

        return TextProcessorOutput(
            result=result,
            original_length=len(input_data.text),
            result_length=len(result),
        )
