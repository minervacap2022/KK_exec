"""GitHub MCP node.

Interacts with GitHub via MCP server.
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
class GitHubIssueInput:
    """Input for GitHub create issue."""

    repo: str
    title: str
    body: str | None = None
    labels: list[str] | None = None


@dataclass
class GitHubIssueOutput:
    """Output from GitHub create issue."""

    success: bool
    issue_number: int
    issue_url: str
    title: str


class GitHubMCPNode(BaseNode[GitHubIssueInput, GitHubIssueOutput]):
    """GitHub MCP node for creating issues.

    Requires 'github_token' credential.
    Uses MCP server for GitHub API calls.

    Example:
        result = await node.run(
            {
                "repo": "owner/repo",
                "title": "Bug: Something is broken",
                "body": "Detailed description..."
            },
            context
        )
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="github_create_issue",
            display_name="GitHub Create Issue",
            description="Create an issue in a GitHub repository",
            category=NodeCategory.MCP,
            credential_type="github_token",
            mcp_server_id="github",
            inputs=[
                NodeInput(
                    name="repo",
                    display_name="Repository",
                    type=NodeInputType.STRING,
                    description="Repository (owner/name)",
                    required=True,
                ),
                NodeInput(
                    name="title",
                    display_name="Title",
                    type=NodeInputType.STRING,
                    description="Issue title",
                    required=True,
                ),
                NodeInput(
                    name="body",
                    display_name="Body",
                    type=NodeInputType.STRING,
                    description="Issue body (markdown)",
                    required=False,
                ),
                NodeInput(
                    name="labels",
                    display_name="Labels",
                    type=NodeInputType.ARRAY,
                    description="Labels to apply",
                    required=False,
                ),
            ],
            outputs=[
                NodeOutput(
                    name="success",
                    display_name="Success",
                    type=NodeOutputType.BOOLEAN,
                    description="Whether issue was created",
                ),
                NodeOutput(
                    name="issue_number",
                    display_name="Issue Number",
                    type=NodeOutputType.NUMBER,
                    description="Created issue number",
                ),
                NodeOutput(
                    name="issue_url",
                    display_name="Issue URL",
                    type=NodeOutputType.STRING,
                    description="URL to the created issue",
                ),
            ],
            tags=["github", "issues", "project-management"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> GitHubIssueInput:
        """Validate input data."""
        repo = input_data.get("repo")
        title = input_data.get("title")
        body = input_data.get("body")
        labels = input_data.get("labels")

        if not repo:
            raise NodeValidationError("Repository is required", field="repo")

        if "/" not in repo:
            raise NodeValidationError(
                "Repository must be in format 'owner/name'", field="repo"
            )

        if not title:
            raise NodeValidationError("Title is required", field="title")

        if labels and not isinstance(labels, list):
            raise NodeValidationError("Labels must be a list", field="labels")

        return GitHubIssueInput(
            repo=repo,
            title=title,
            body=body,
            labels=labels,
        )

    async def execute(
        self,
        input_data: GitHubIssueInput,
        context: NodeContext,
    ) -> GitHubIssueOutput:
        """Execute GitHub issue creation via MCP."""
        token = context.credentials.get("token")
        if not token:
            raise NodeExecutionError(
                message="GitHub token not found in credentials",
                node_name="github_create_issue",
                error_code="MISSING_CREDENTIAL",
            )

        # TODO: Implement actual MCP call
        # Placeholder response
        return GitHubIssueOutput(
            success=True,
            issue_number=123,
            issue_url=f"https://github.com/{input_data.repo}/issues/123",
            title=input_data.title,
        )
