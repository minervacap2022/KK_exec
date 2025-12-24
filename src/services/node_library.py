"""Node library service.

Manages discovery, registration, and categorization of workflow nodes.
Loads built-in nodes and provides node catalog for workflow building.
"""

from typing import Any

import structlog

from src.models.node import NodeCategory, NodeDefinition, NodeInput, NodeInputType, NodeOutput, NodeOutputType

logger = structlog.get_logger()


class NodeLibraryError(Exception):
    """Error in node library operations."""

    pass


class NodeLibrary:
    """Node library for workflow building.

    Manages available nodes with:
    - Built-in node definitions
    - Dynamic node registration
    - Category-based organization
    - Credential requirement tracking

    Example usage:
        library = NodeLibrary()
        library.load_builtin_nodes()

        all_nodes = library.get_all_nodes()
        mcp_nodes = library.get_nodes_by_category(NodeCategory.MCP)
        slack_nodes = library.get_nodes_for_mcp_server("slack")
    """

    def __init__(self) -> None:
        """Initialize empty node library."""
        self._nodes: dict[str, NodeDefinition] = {}
        self._by_category: dict[NodeCategory, list[str]] = {
            cat: [] for cat in NodeCategory
        }
        self._by_mcp_server: dict[str, list[str]] = {}
        self._by_credential: dict[str, list[str]] = {}

    def register(self, node: NodeDefinition) -> None:
        """Register a node in the library.

        Args:
            node: Node definition to register

        Raises:
            NodeLibraryError: If node with same name exists
        """
        if node.name in self._nodes:
            raise NodeLibraryError(f"Node '{node.name}' already registered")

        self._nodes[node.name] = node
        self._by_category[node.category].append(node.name)

        if node.mcp_server_id:
            if node.mcp_server_id not in self._by_mcp_server:
                self._by_mcp_server[node.mcp_server_id] = []
            self._by_mcp_server[node.mcp_server_id].append(node.name)

        if node.credential_type:
            if node.credential_type not in self._by_credential:
                self._by_credential[node.credential_type] = []
            self._by_credential[node.credential_type].append(node.name)

        logger.debug(
            "node_registered",
            name=node.name,
            category=node.category.value,
            credential_type=node.credential_type,
        )

    def unregister(self, name: str) -> None:
        """Remove a node from the library.

        Args:
            name: Node name to remove
        """
        if name not in self._nodes:
            return

        node = self._nodes[name]
        del self._nodes[name]

        self._by_category[node.category].remove(name)

        if node.mcp_server_id and name in self._by_mcp_server.get(node.mcp_server_id, []):
            self._by_mcp_server[node.mcp_server_id].remove(name)

        if node.credential_type and name in self._by_credential.get(node.credential_type, []):
            self._by_credential[node.credential_type].remove(name)

    def get(self, name: str) -> NodeDefinition | None:
        """Get a node by name.

        Args:
            name: Node name

        Returns:
            NodeDefinition or None if not found
        """
        return self._nodes.get(name)

    def get_all_nodes(self) -> list[NodeDefinition]:
        """Get all registered nodes.

        Returns:
            List of all node definitions
        """
        return list(self._nodes.values())

    def get_nodes_by_category(self, category: NodeCategory) -> list[NodeDefinition]:
        """Get nodes by category.

        Args:
            category: Node category

        Returns:
            List of nodes in category
        """
        return [self._nodes[name] for name in self._by_category[category]]

    def get_nodes_for_mcp_server(self, mcp_server_id: str) -> list[NodeDefinition]:
        """Get nodes for a specific MCP server.

        Args:
            mcp_server_id: MCP server identifier

        Returns:
            List of nodes for that server
        """
        names = self._by_mcp_server.get(mcp_server_id, [])
        return [self._nodes[name] for name in names]

    def get_nodes_by_credential(self, credential_type: str) -> list[NodeDefinition]:
        """Get nodes requiring a specific credential type.

        Args:
            credential_type: Credential type

        Returns:
            List of nodes requiring that credential
        """
        names = self._by_credential.get(credential_type, [])
        return [self._nodes[name] for name in names]

    def get_available_nodes(
        self,
        available_credentials: list[str] | None = None,
    ) -> list[NodeDefinition]:
        """Get nodes available to a user based on their credentials.

        Args:
            available_credentials: User's available credential types

        Returns:
            List of available nodes
        """
        available_credentials = available_credentials or []

        return [
            node
            for node in self._nodes.values()
            if node.credential_type is None or node.credential_type in available_credentials
        ]

    def get_catalog(self) -> dict[str, Any]:
        """Get complete node catalog for API response.

        Returns:
            Dictionary with nodes organized by category
        """
        return {
            "categories": {
                category.value: [
                    self._nodes[name].to_dict()
                    for name in self._by_category[category]
                ]
                for category in NodeCategory
            },
            "total_count": len(self._nodes),
            "by_credential": {
                cred_type: len(names)
                for cred_type, names in self._by_credential.items()
            },
            "by_mcp_server": {
                server_id: len(names)
                for server_id, names in self._by_mcp_server.items()
            },
        }

    def load_builtin_nodes(self) -> int:
        """Load all built-in node definitions.

        Returns:
            Number of nodes loaded
        """
        builtin_nodes = self._get_builtin_nodes()

        for node in builtin_nodes:
            try:
                self.register(node)
            except NodeLibraryError as e:
                logger.warning("builtin_node_registration_failed", error=str(e))

        logger.info("builtin_nodes_loaded", count=len(builtin_nodes))
        return len(builtin_nodes)

    def _get_builtin_nodes(self) -> list[NodeDefinition]:
        """Get built-in node definitions."""
        return [
            # Tool nodes (no auth required)
            NodeDefinition(
                name="calculator",
                display_name="Calculator",
                description="Perform mathematical calculations",
                category=NodeCategory.TOOL,
                inputs=[
                    NodeInput(
                        name="expression",
                        display_name="Expression",
                        type=NodeInputType.STRING,
                        description="Mathematical expression to evaluate",
                    )
                ],
                outputs=[
                    NodeOutput(
                        name="result",
                        display_name="Result",
                        type=NodeOutputType.NUMBER,
                        description="Calculation result",
                    )
                ],
                tags=["math", "calculation"],
            ),
            NodeDefinition(
                name="text_processor",
                display_name="Text Processor",
                description="Process and transform text",
                category=NodeCategory.TOOL,
                inputs=[
                    NodeInput(
                        name="text",
                        display_name="Text",
                        type=NodeInputType.STRING,
                        description="Input text to process",
                    ),
                    NodeInput(
                        name="operation",
                        display_name="Operation",
                        type=NodeInputType.STRING,
                        description="Processing operation",
                        options=["uppercase", "lowercase", "trim", "reverse"],
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="result",
                        display_name="Result",
                        type=NodeOutputType.STRING,
                        description="Processed text",
                    )
                ],
                tags=["text", "string", "transform"],
            ),
            NodeDefinition(
                name="json_transformer",
                display_name="JSON Transformer",
                description="Transform JSON data using JSONPath",
                category=NodeCategory.TOOL,
                inputs=[
                    NodeInput(
                        name="data",
                        display_name="JSON Data",
                        type=NodeInputType.JSON,
                        description="Input JSON data",
                    ),
                    NodeInput(
                        name="path",
                        display_name="JSONPath",
                        type=NodeInputType.STRING,
                        description="JSONPath expression",
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="result",
                        display_name="Result",
                        type=NodeOutputType.JSON,
                        description="Transformed data",
                    )
                ],
                tags=["json", "transform", "extract"],
            ),
            # API nodes (API key required)
            NodeDefinition(
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
                    ),
                    NodeInput(
                        name="model",
                        display_name="Model",
                        type=NodeInputType.STRING,
                        description="Model to use",
                        default="gpt-4o",
                        required=False,
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="response",
                        display_name="Response",
                        type=NodeOutputType.STRING,
                        description="Model response",
                    )
                ],
                tags=["ai", "llm", "text-generation"],
            ),
            NodeDefinition(
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
                    ),
                    NodeInput(
                        name="model",
                        display_name="Model",
                        type=NodeInputType.STRING,
                        description="Model to use",
                        default="claude-3-opus-20240229",
                        required=False,
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="response",
                        display_name="Response",
                        type=NodeOutputType.STRING,
                        description="Model response",
                    )
                ],
                tags=["ai", "llm", "text-generation"],
            ),
            NodeDefinition(
                name="weather_api",
                display_name="Weather API",
                description="Get weather data for a location",
                category=NodeCategory.API,
                credential_type="weather_api_key",
                inputs=[
                    NodeInput(
                        name="location",
                        display_name="Location",
                        type=NodeInputType.STRING,
                        description="City name or coordinates",
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="weather",
                        display_name="Weather Data",
                        type=NodeOutputType.JSON,
                        description="Weather information",
                    )
                ],
                tags=["weather", "api", "data"],
            ),
            # MCP nodes (user-specific auth)
            NodeDefinition(
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
                        description="Channel name or ID",
                    ),
                    NodeInput(
                        name="message",
                        display_name="Message",
                        type=NodeInputType.STRING,
                        description="Message content",
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="result",
                        display_name="Result",
                        type=NodeOutputType.JSON,
                        description="Send result",
                    )
                ],
                tags=["slack", "messaging", "communication"],
            ),
            NodeDefinition(
                name="slack_list_channels",
                display_name="Slack List Channels",
                description="List Slack channels",
                category=NodeCategory.MCP,
                credential_type="slack_oauth",
                mcp_server_id="slack",
                inputs=[],
                outputs=[
                    NodeOutput(
                        name="channels",
                        display_name="Channels",
                        type=NodeOutputType.ARRAY,
                        description="List of channels",
                    )
                ],
                tags=["slack", "channels"],
            ),
            NodeDefinition(
                name="github_create_issue",
                display_name="GitHub Create Issue",
                description="Create a GitHub issue",
                category=NodeCategory.MCP,
                credential_type="github_token",
                mcp_server_id="github",
                inputs=[
                    NodeInput(
                        name="repo",
                        display_name="Repository",
                        type=NodeInputType.STRING,
                        description="Repository (owner/name)",
                    ),
                    NodeInput(
                        name="title",
                        display_name="Title",
                        type=NodeInputType.STRING,
                        description="Issue title",
                    ),
                    NodeInput(
                        name="body",
                        display_name="Body",
                        type=NodeInputType.STRING,
                        description="Issue body",
                        required=False,
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="issue",
                        display_name="Issue",
                        type=NodeOutputType.JSON,
                        description="Created issue",
                    )
                ],
                tags=["github", "issues", "project-management"],
            ),
            NodeDefinition(
                name="github_search_repos",
                display_name="GitHub Search Repos",
                description="Search GitHub repositories",
                category=NodeCategory.MCP,
                credential_type="github_token",
                mcp_server_id="github",
                inputs=[
                    NodeInput(
                        name="query",
                        display_name="Search Query",
                        type=NodeInputType.STRING,
                        description="Search query",
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="repos",
                        display_name="Repositories",
                        type=NodeOutputType.ARRAY,
                        description="Search results",
                    )
                ],
                tags=["github", "search", "repositories"],
            ),
            NodeDefinition(
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
                        description="Path to file",
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="content",
                        display_name="Content",
                        type=NodeOutputType.STRING,
                        description="File content",
                    )
                ],
                tags=["filesystem", "file", "read"],
            ),
            NodeDefinition(
                name="filesystem_write",
                display_name="Write File",
                description="Write contents to a file",
                category=NodeCategory.MCP,
                mcp_server_id="filesystem",
                inputs=[
                    NodeInput(
                        name="path",
                        display_name="File Path",
                        type=NodeInputType.STRING,
                        description="Path to file",
                    ),
                    NodeInput(
                        name="content",
                        display_name="Content",
                        type=NodeInputType.STRING,
                        description="Content to write",
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="success",
                        display_name="Success",
                        type=NodeOutputType.BOOLEAN,
                        description="Write success",
                    )
                ],
                tags=["filesystem", "file", "write"],
            ),
            # Notion MCP nodes
            NodeDefinition(
                name="notion_create_page",
                display_name="Notion Create Page",
                description="Create a new page in Notion",
                category=NodeCategory.MCP,
                credential_type="notion_oauth",
                mcp_server_id="notion",
                inputs=[
                    NodeInput(
                        name="title",
                        display_name="Page Title",
                        type=NodeInputType.STRING,
                        description="Title of the new page",
                    ),
                    NodeInput(
                        name="content",
                        display_name="Page Content",
                        type=NodeInputType.STRING,
                        description="Content of the page (markdown or plain text)",
                        required=False,
                    ),
                    NodeInput(
                        name="parent_page_id",
                        display_name="Parent Page ID",
                        type=NodeInputType.STRING,
                        description="ID of parent page (optional, defaults to workspace)",
                        required=False,
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="page_id",
                        display_name="Page ID",
                        type=NodeOutputType.STRING,
                        description="ID of created page",
                    ),
                    NodeOutput(
                        name="url",
                        display_name="Page URL",
                        type=NodeOutputType.STRING,
                        description="URL to the created page",
                    ),
                ],
                tags=["notion", "page", "create", "mcp"],
            ),
            NodeDefinition(
                name="notion_search",
                display_name="Notion Search",
                description="Search for pages and databases in Notion",
                category=NodeCategory.MCP,
                credential_type="notion_oauth",
                mcp_server_id="notion",
                inputs=[
                    NodeInput(
                        name="query",
                        display_name="Search Query",
                        type=NodeInputType.STRING,
                        description="Text to search for",
                    ),
                    NodeInput(
                        name="filter_type",
                        display_name="Filter Type",
                        type=NodeInputType.STRING,
                        description="Filter by type (page, database)",
                        required=False,
                    ),
                ],
                outputs=[
                    NodeOutput(
                        name="results",
                        display_name="Search Results",
                        type=NodeOutputType.ARRAY,
                        description="List of matching items",
                    ),
                    NodeOutput(
                        name="total_count",
                        display_name="Total Count",
                        type=NodeOutputType.NUMBER,
                        description="Number of results found",
                    ),
                ],
                tags=["notion", "search", "mcp"],
            ),
        ]


# Singleton instance
_library: NodeLibrary | None = None


def get_node_library() -> NodeLibrary:
    """Get or create the singleton node library.

    Returns:
        NodeLibrary instance with builtin nodes loaded
    """
    global _library
    if _library is None:
        _library = NodeLibrary()
        _library.load_builtin_nodes()
    return _library
