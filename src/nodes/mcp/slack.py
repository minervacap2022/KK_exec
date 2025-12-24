"""Slack MCP node.

Interacts with Slack via MCP server.
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
class SlackMessageInput:
    """Input for Slack send message."""

    channel: str
    message: str


@dataclass
class SlackMessageOutput:
    """Output from Slack send message."""

    success: bool
    channel: str
    ts: str  # Message timestamp/ID
    message: str


class SlackMCPNode(BaseNode[SlackMessageInput, SlackMessageOutput]):
    """Slack MCP node for sending messages.

    Requires 'slack_oauth' credential.
    Uses MCP server for actual Slack API calls.

    Example:
        result = await node.run(
            {"channel": "#general", "message": "Hello from workflow!"},
            context
        )
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="slack_send_message",
            display_name="Slack Send Message",
            description="Send a message to a Slack channel",
            category=NodeCategory.MCP,
            credential_type="slack_oauth",
            mcp_server_id="slack",
            inputs=[
                NodeInput(
                    name="channel",
                    display_name="Channel",
                    type=NodeInputType.STRING,
                    description="Channel name (e.g., #general) or ID",
                    required=True,
                ),
                NodeInput(
                    name="message",
                    display_name="Message",
                    type=NodeInputType.STRING,
                    description="Message content",
                    required=True,
                ),
            ],
            outputs=[
                NodeOutput(
                    name="success",
                    display_name="Success",
                    type=NodeOutputType.BOOLEAN,
                    description="Whether message was sent",
                ),
                NodeOutput(
                    name="channel",
                    display_name="Channel",
                    type=NodeOutputType.STRING,
                    description="Channel where message was sent",
                ),
                NodeOutput(
                    name="ts",
                    display_name="Timestamp",
                    type=NodeOutputType.STRING,
                    description="Message timestamp/ID",
                ),
            ],
            tags=["slack", "messaging", "communication"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> SlackMessageInput:
        """Validate input data."""
        channel = input_data.get("channel")
        message = input_data.get("message")

        if not channel:
            raise NodeValidationError("Channel is required", field="channel")

        if not message:
            raise NodeValidationError("Message is required", field="message")

        return SlackMessageInput(channel=channel, message=message)

    async def execute(
        self,
        input_data: SlackMessageInput,
        context: NodeContext,
    ) -> SlackMessageOutput:
        """Execute Slack message send via MCP.

        Note: This is a placeholder. In production, this would:
        1. Get MCP gateway from context
        2. Connect to Slack MCP server with user credentials
        3. Call the send_message tool
        """
        # Check credentials
        access_token = context.credentials.get("access_token")
        if not access_token:
            raise NodeExecutionError(
                message="Slack OAuth token not found in credentials",
                node_name="slack_send_message",
                error_code="MISSING_CREDENTIAL",
            )

        # TODO: Implement actual MCP call
        # For now, return placeholder
        return SlackMessageOutput(
            success=True,
            channel=input_data.channel,
            ts="1234567890.123456",
            message=input_data.message,
        )
