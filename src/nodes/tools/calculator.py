"""Calculator node.

Performs mathematical calculations.
"""

import ast
import operator
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
class CalculatorInput:
    """Input for calculator node."""

    expression: str


@dataclass
class CalculatorOutput:
    """Output from calculator node."""

    result: float


# Safe operators for expression evaluation
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(node: ast.AST) -> float:
    """Safely evaluate an AST node.

    Only allows basic arithmetic operations.

    Args:
        node: AST node

    Returns:
        Evaluation result

    Raises:
        ValueError: If operation is not allowed
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Invalid constant: {node.value}")

    if isinstance(node, ast.BinOp):
        left = safe_eval(node.left)
        right = safe_eval(node.right)
        op = SAFE_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        operand = safe_eval(node.operand)
        op = SAFE_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(operand)

    if isinstance(node, ast.Expression):
        return safe_eval(node.body)

    raise ValueError(f"Unsupported expression: {type(node).__name__}")


class CalculatorNode(BaseNode[CalculatorInput, CalculatorOutput]):
    """Calculator node for mathematical expressions.

    Supports: +, -, *, /, //, %, **
    Parentheses for grouping

    Example:
        result = await node.run({"expression": "(1 + 2) * 3"}, context)
        # result = {"result": 9.0}
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="calculator",
            display_name="Calculator",
            description="Perform mathematical calculations safely",
            category=NodeCategory.TOOL,
            inputs=[
                NodeInput(
                    name="expression",
                    display_name="Expression",
                    type=NodeInputType.STRING,
                    description="Mathematical expression (e.g., '(1 + 2) * 3')",
                    required=True,
                ),
            ],
            outputs=[
                NodeOutput(
                    name="result",
                    display_name="Result",
                    type=NodeOutputType.NUMBER,
                    description="Calculation result",
                ),
            ],
            tags=["math", "calculation", "arithmetic"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> CalculatorInput:
        """Validate input data."""
        expression = input_data.get("expression")

        if not expression:
            raise NodeValidationError("Expression is required", field="expression")

        if not isinstance(expression, str):
            raise NodeValidationError(
                "Expression must be a string", field="expression"
            )

        # Check for dangerous patterns
        dangerous = ["import", "exec", "eval", "__", "open", "file"]
        expr_lower = expression.lower()
        for pattern in dangerous:
            if pattern in expr_lower:
                raise NodeValidationError(
                    f"Expression contains forbidden pattern: {pattern}",
                    field="expression",
                )

        return CalculatorInput(expression=expression)

    async def execute(
        self,
        input_data: CalculatorInput,
        context: NodeContext,
    ) -> CalculatorOutput:
        """Execute the calculation."""
        try:
            # Parse expression to AST
            tree = ast.parse(input_data.expression, mode="eval")

            # Safely evaluate
            result = safe_eval(tree)

            return CalculatorOutput(result=result)

        except SyntaxError as e:
            raise NodeExecutionError(
                message=f"Invalid expression syntax: {str(e)}",
                node_name="calculator",
                error_code="SYNTAX_ERROR",
            ) from e
        except ValueError as e:
            raise NodeExecutionError(
                message=str(e),
                node_name="calculator",
                error_code="EVALUATION_ERROR",
            ) from e
        except ZeroDivisionError as e:
            raise NodeExecutionError(
                message="Division by zero",
                node_name="calculator",
                error_code="DIVISION_BY_ZERO",
            ) from e
