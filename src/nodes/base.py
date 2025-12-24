"""Base node interface.

Defines the abstract base class for all workflow nodes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import structlog

from src.models.node import NodeCategory, NodeDefinition, NodeInput, NodeOutput

logger = structlog.get_logger()

# Type variables for input/output schemas
InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class NodeExecutionError(Exception):
    """Error during node execution."""

    def __init__(
        self,
        message: str,
        node_name: str,
        error_code: str = "NODE_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.node_name = node_name
        self.error_code = error_code
        self.details = details or {}


class NodeValidationError(Exception):
    """Error validating node input."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


@dataclass
class NodeContext:
    """Context passed to node during execution.

    Contains user credentials, execution metadata, and shared state.
    """

    user_id: str
    execution_id: str
    credentials: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None


class BaseNode(ABC, Generic[InputT, OutputT]):
    """Abstract base class for workflow nodes.

    All nodes must implement:
    - get_definition(): Returns node metadata
    - execute(): Performs the node's operation

    Example implementation:
        class CalculatorNode(BaseNode[CalculatorInput, CalculatorOutput]):
            def get_definition(self) -> NodeDefinition:
                return NodeDefinition(
                    name="calculator",
                    display_name="Calculator",
                    category=NodeCategory.TOOL,
                    ...
                )

            async def execute(
                self,
                input_data: CalculatorInput,
                context: NodeContext,
            ) -> CalculatorOutput:
                result = eval(input_data.expression)  # Simplified
                return CalculatorOutput(result=result)
    """

    @abstractmethod
    def get_definition(self) -> NodeDefinition:
        """Get the node definition with metadata.

        Returns:
            NodeDefinition with name, category, inputs, outputs, etc.
        """
        pass

    @abstractmethod
    async def execute(
        self,
        input_data: InputT,
        context: NodeContext,
    ) -> OutputT:
        """Execute the node's operation.

        Args:
            input_data: Validated input data
            context: Execution context with credentials and metadata

        Returns:
            Node output

        Raises:
            NodeExecutionError: If execution fails
            NodeValidationError: If input validation fails
        """
        pass

    def validate_input(self, input_data: dict[str, Any]) -> InputT:
        """Validate and transform input data.

        Override this method to implement custom validation.

        Args:
            input_data: Raw input dictionary

        Returns:
            Validated input (typed)

        Raises:
            NodeValidationError: If validation fails
        """
        # Default implementation: return as-is
        return input_data  # type: ignore

    def validate_output(self, output_data: OutputT) -> dict[str, Any]:
        """Validate and transform output data.

        Override this method to implement custom output validation.

        Args:
            output_data: Node output

        Returns:
            Output as dictionary
        """
        if isinstance(output_data, dict):
            return output_data
        return {"result": output_data}

    async def pre_execute(self, context: NodeContext) -> None:
        """Called before execute(). Override for setup logic.

        Args:
            context: Execution context
        """
        pass

    async def post_execute(
        self,
        output_data: OutputT,
        context: NodeContext,
    ) -> None:
        """Called after execute(). Override for cleanup logic.

        Args:
            output_data: Node output
            context: Execution context
        """
        pass

    async def run(
        self,
        input_data: dict[str, Any],
        context: NodeContext,
    ) -> dict[str, Any]:
        """Run the node with full lifecycle.

        This method handles:
        1. Input validation
        2. Pre-execute hook
        3. Execution
        4. Post-execute hook
        5. Output validation

        Args:
            input_data: Raw input dictionary
            context: Execution context

        Returns:
            Output dictionary

        Raises:
            NodeExecutionError: If execution fails
            NodeValidationError: If validation fails
        """
        definition = self.get_definition()

        logger.debug(
            "node_execution_starting",
            node_name=definition.name,
            execution_id=context.execution_id,
        )

        try:
            # Validate input
            validated_input = self.validate_input(input_data)

            # Pre-execute hook
            await self.pre_execute(context)

            # Execute
            output = await self.execute(validated_input, context)

            # Post-execute hook
            await self.post_execute(output, context)

            # Validate and return output
            result = self.validate_output(output)

            logger.debug(
                "node_execution_completed",
                node_name=definition.name,
                execution_id=context.execution_id,
            )

            return result

        except NodeExecutionError:
            raise
        except NodeValidationError as e:
            raise NodeExecutionError(
                message=str(e),
                node_name=definition.name,
                error_code="VALIDATION_ERROR",
                details={"field": e.field},
            ) from e
        except Exception as e:
            logger.exception(
                "node_execution_failed",
                node_name=definition.name,
                execution_id=context.execution_id,
            )
            raise NodeExecutionError(
                message=str(e),
                node_name=definition.name,
                error_code="EXECUTION_ERROR",
            ) from e

    @property
    def name(self) -> str:
        """Get node name."""
        return self.get_definition().name

    @property
    def category(self) -> NodeCategory:
        """Get node category."""
        return self.get_definition().category

    @property
    def credential_type(self) -> str | None:
        """Get required credential type."""
        return self.get_definition().credential_type

    def to_tool(self) -> "BaseTool":
        """Convert node to LangChain tool.

        Returns:
            LangChain-compatible tool
        """
        from langchain_core.tools import StructuredTool

        definition = self.get_definition()

        # Build input schema from node inputs
        input_schema = {}
        for inp in definition.inputs:
            input_schema[inp.name] = {
                "description": inp.description,
                "type": inp.type.value,
            }

        async def _run_tool(**kwargs: Any) -> dict[str, Any]:
            # This will be called with a real context during execution
            dummy_context = NodeContext(
                user_id="",
                execution_id="",
            )
            return await self.run(kwargs, dummy_context)

        return StructuredTool.from_function(
            func=lambda **kwargs: None,  # Sync placeholder
            coroutine=_run_tool,
            name=definition.name,
            description=definition.description,
        )
