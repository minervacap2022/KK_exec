"""OpenAI API node.

Calls OpenAI GPT models for text generation.
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
class OpenAIInput:
    """Input for OpenAI node."""

    prompt: str
    model: str = "gpt-4o"
    max_tokens: int = 1024
    temperature: float = 0.7


@dataclass
class OpenAIOutput:
    """Output from OpenAI node."""

    response: str
    model: str
    usage: dict[str, int]


class OpenAINode(BaseNode[OpenAIInput, OpenAIOutput]):
    """OpenAI API node for text generation.

    Requires 'openai_api_key' credential.

    Example:
        result = await node.run(
            {"prompt": "Write a haiku about coding"},
            context  # Must include OpenAI API key in credentials
        )
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="openai_chat",
            display_name="OpenAI Chat",
            description="Generate text using OpenAI GPT models",
            category=NodeCategory.API,
            credential_type="openai_api_key",
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
                    default="gpt-4o",
                    options=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
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
                    description="Sampling temperature (0-2)",
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
            ],
            tags=["ai", "llm", "text-generation", "openai"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> OpenAIInput:
        """Validate input data."""
        prompt = input_data.get("prompt")

        if not prompt:
            raise NodeValidationError("Prompt is required", field="prompt")

        if not isinstance(prompt, str):
            raise NodeValidationError("Prompt must be a string", field="prompt")

        model = input_data.get("model", "gpt-4o")
        max_tokens = input_data.get("max_tokens", 1024)
        temperature = input_data.get("temperature", 0.7)

        if not 0 <= temperature <= 2:
            raise NodeValidationError(
                "Temperature must be between 0 and 2", field="temperature"
            )

        if max_tokens < 1 or max_tokens > 128000:
            raise NodeValidationError(
                "Max tokens must be between 1 and 128000", field="max_tokens"
            )

        return OpenAIInput(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def execute(
        self,
        input_data: OpenAIInput,
        context: NodeContext,
    ) -> OpenAIOutput:
        """Execute OpenAI API call."""
        # Get API key from credentials
        api_key = context.credentials.get("api_key")
        if not api_key:
            raise NodeExecutionError(
                message="OpenAI API key not found in credentials",
                node_name="openai_chat",
                error_code="MISSING_CREDENTIAL",
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
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

                return OpenAIOutput(
                    response=data["choices"][0]["message"]["content"],
                    model=data["model"],
                    usage=data.get("usage", {}),
                )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise NodeExecutionError(
                    message="Invalid OpenAI API key",
                    node_name="openai_chat",
                    error_code="AUTH_ERROR",
                ) from e
            raise NodeExecutionError(
                message=f"OpenAI API error: {e.response.text}",
                node_name="openai_chat",
                error_code="API_ERROR",
            ) from e
        except httpx.RequestError as e:
            raise NodeExecutionError(
                message=f"Request failed: {str(e)}",
                node_name="openai_chat",
                error_code="NETWORK_ERROR",
            ) from e
