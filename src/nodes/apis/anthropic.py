"""Anthropic API node.

Calls Anthropic Claude models for text generation.
"""

from dataclasses import dataclass
from typing import Any

import httpx

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
class AnthropicInput:
    """Input for Anthropic node."""

    prompt: str
    model: str = "claude-3-opus-20240229"
    max_tokens: int = 1024
    temperature: float = 0.7


@dataclass
class AnthropicOutput:
    """Output from Anthropic node."""

    response: str
    model: str
    usage: dict[str, int]
    stop_reason: str


class AnthropicNode(BaseNode[AnthropicInput, AnthropicOutput]):
    """Anthropic API node for text generation.

    Requires 'anthropic_api_key' credential.

    Example:
        result = await node.run(
            {"prompt": "Explain quantum computing"},
            context  # Must include Anthropic API key in credentials
        )
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="anthropic_chat",
            display_name="Anthropic Claude",
            description="Generate text using Anthropic Claude models",
            category=NodeCategory.API,
            credential_type="anthropic_api_key",
            inputs=[
                NodeInput(
                    name="prompt",
                    display_name="Prompt",
                    type=NodeInputType.STRING,
                    description="Input prompt for the model",
                    required=True,
                ),
                NodeInput(
                    name="model",
                    display_name="Model",
                    type=NodeInputType.STRING,
                    description="Model to use",
                    required=False,
                    default="claude-3-opus-20240229",
                    options=[
                        "claude-3-opus-20240229",
                        "claude-3-sonnet-20240229",
                        "claude-3-haiku-20240307",
                    ],
                ),
                NodeInput(
                    name="max_tokens",
                    display_name="Max Tokens",
                    type=NodeInputType.NUMBER,
                    description="Maximum tokens in response",
                    required=False,
                    default=1024,
                ),
                NodeInput(
                    name="temperature",
                    display_name="Temperature",
                    type=NodeInputType.NUMBER,
                    description="Sampling temperature (0-1)",
                    required=False,
                    default=0.7,
                ),
            ],
            outputs=[
                NodeOutput(
                    name="response",
                    display_name="Response",
                    type=NodeOutputType.STRING,
                    description="Model response",
                ),
                NodeOutput(
                    name="model",
                    display_name="Model Used",
                    type=NodeOutputType.STRING,
                    description="Actual model used",
                ),
                NodeOutput(
                    name="usage",
                    display_name="Token Usage",
                    type=NodeOutputType.JSON,
                    description="Token usage statistics",
                ),
                NodeOutput(
                    name="stop_reason",
                    display_name="Stop Reason",
                    type=NodeOutputType.STRING,
                    description="Why generation stopped",
                ),
            ],
            tags=["ai", "llm", "text-generation", "anthropic", "claude"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> AnthropicInput:
        """Validate input data."""
        prompt = input_data.get("prompt")

        if not prompt:
            raise NodeValidationError("Prompt is required", field="prompt")

        if not isinstance(prompt, str):
            raise NodeValidationError("Prompt must be a string", field="prompt")

        model = input_data.get("model", "claude-3-opus-20240229")
        max_tokens = input_data.get("max_tokens", 1024)
        temperature = input_data.get("temperature", 0.7)

        if not 0 <= temperature <= 1:
            raise NodeValidationError(
                "Temperature must be between 0 and 1", field="temperature"
            )

        if max_tokens < 1 or max_tokens > 4096:
            raise NodeValidationError(
                "Max tokens must be between 1 and 4096", field="max_tokens"
            )

        return AnthropicInput(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def execute(
        self,
        input_data: AnthropicInput,
        context: NodeContext,
    ) -> AnthropicOutput:
        """Execute Anthropic API call."""
        api_key = context.credentials.get("api_key")
        if not api_key:
            raise NodeExecutionError(
                message="Anthropic API key not found in credentials",
                node_name="anthropic_chat",
                error_code="MISSING_CREDENTIAL",
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": input_data.model,
                        "messages": [{"role": "user", "content": input_data.prompt}],
                        "max_tokens": input_data.max_tokens,
                        "temperature": input_data.temperature,
                    },
                    timeout=60.0,
                )

                response.raise_for_status()
                data = response.json()

                # Extract text from content blocks
                text = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        text += block.get("text", "")

                return AnthropicOutput(
                    response=text,
                    model=data["model"],
                    usage=data.get("usage", {}),
                    stop_reason=data.get("stop_reason", ""),
                )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise NodeExecutionError(
                    message="Invalid Anthropic API key",
                    node_name="anthropic_chat",
                    error_code="AUTH_ERROR",
                ) from e
            raise NodeExecutionError(
                message=f"Anthropic API error: {e.response.text}",
                node_name="anthropic_chat",
                error_code="API_ERROR",
            ) from e
        except httpx.RequestError as e:
            raise NodeExecutionError(
                message=f"Request failed: {str(e)}",
                node_name="anthropic_chat",
                error_code="NETWORK_ERROR",
            ) from e
