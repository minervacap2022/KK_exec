"""Notion MCP node.

Interacts with Notion via MCP server.
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
class NotionCreatePageInput:
    """Input for creating a Notion page."""

    title: str
    content: str | None = None
    parent_page_id: str | None = None


@dataclass
class NotionCreatePageOutput:
    """Output from creating a Notion page."""

    success: bool
    page_id: str
    url: str
    title: str


class NotionCreatePageNode(BaseNode[NotionCreatePageInput, NotionCreatePageOutput]):
    """Notion MCP node for creating pages.

    Requires 'notion_oauth' credential.
    Uses MCP server for actual Notion API calls.

    Example:
        result = await node.run(
            {"title": "Meeting Notes", "content": "Discussion points..."},
            context
        )
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
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
                    required=True,
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
                    name="success",
                    display_name="Success",
                    type=NodeOutputType.BOOLEAN,
                    description="Whether page was created successfully",
                ),
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
                NodeOutput(
                    name="title",
                    display_name="Page Title",
                    type=NodeOutputType.STRING,
                    description="Title of created page",
                ),
            ],
            tags=["notion", "page", "create", "mcp"],
        )

    def _convert_content_to_blocks(self, content: str) -> list[dict[str, Any]]:
        """Convert plain text content to Notion block format.

        Args:
            content: Plain text or markdown content

        Returns:
            List of Notion block objects
        """
        import structlog
        logger = structlog.get_logger()

        if not content:
            return []

        blocks = []
        lines = content.split("\n")

        for line in lines:
            if not line:
                # Empty line creates an empty paragraph block
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": []
                    }
                })
            elif line.startswith("# "):
                # Heading 1
                blocks.append({
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": line[2:].strip()}
                            }
                        ]
                    }
                })
            elif line.startswith("## "):
                # Heading 2
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": line[3:].strip()}
                            }
                        ]
                    }
                })
            elif line.startswith("### "):
                # Heading 3
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": line[4:].strip()}
                            }
                        ]
                    }
                })
            elif line.startswith("- ") or line.startswith("* "):
                # Bulleted list item
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": line[2:].strip()}
                            }
                        ]
                    }
                })
            elif line.startswith("1. ") or line.startswith("2. ") or line.startswith("3. ") or \
                 line.startswith("4. ") or line.startswith("5. ") or line.startswith("6. ") or \
                 line.startswith("7. ") or line.startswith("8. ") or line.startswith("9. "):
                # Numbered list item
                blocks.append({
                    "object": "block",
                    "type": "numbered_list_item",
                    "numbered_list_item": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": line.split(". ", 1)[1].strip()}
                            }
                        ]
                    }
                })
            elif line.startswith("```"):
                # Code block - skip the delimiters and capture content
                continue
            else:
                # Regular paragraph
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": line}
                            }
                        ]
                    }
                })

        logger.debug(
            "notion_content_converted_to_blocks",
            block_count=len(blocks),
            line_count=len(lines),
        )

        return blocks

    async def execute(
        self,
        input_data: NotionCreatePageInput,
        context: NodeContext,
    ) -> NotionCreatePageOutput:
        """Execute node.

        Args:
            input_data: Input data
            context: Execution context with credentials

        Returns:
            Output data

        Raises:
            NodeExecutionError: If execution fails
        """
        # Validate credentials
        import structlog
        logger = structlog.get_logger()
        logger.info(
            "notion_node_checking_credentials",
            available_creds=list(context.credentials.keys()),
            has_notion=("notion_oauth" in context.credentials),
        )

        if "notion_oauth" not in context.credentials:
            raise NodeValidationError("Missing required credential: notion_oauth")

        # Import gateway here to avoid circular dependency
        from src.services.mcp_gateway import MCPGateway

        # Get Notion credentials
        notion_creds = context.credentials["notion_oauth"]

        # Connect to Notion MCP server using context manager for proper cleanup
        gateway = MCPGateway()

        try:
            async with gateway.connection("notion", notion_creds) as connection:
                # Log available tools for debugging
                logger.info(
                    "notion_mcp_connected",
                    tool_count=len(connection.tools),
                    tools=[t.name for t in connection.tools],
                )

                import json

                # If no parent page specified, we need to search for one
                if not input_data.parent_page_id:
                    # Search for pages to find a suitable parent
                    search_result = await gateway.call_tool(
                        connection,
                        "API-post-search",
                        {"filter": {"value": "page", "property": "object"}},
                    )
                    search_content = search_result.get("content", [])
                    if search_content:
                        search_data = json.loads(search_content[0]["text"])
                        pages = search_data.get("results", [])
                        if pages:
                            # Use first available page as parent
                            input_data.parent_page_id = pages[0].get("id")
                            logger.info(
                                "notion_using_default_parent",
                                parent_id=input_data.parent_page_id,
                            )

                if not input_data.parent_page_id:
                    raise NodeExecutionError(
                        "No parent page available. The Notion API requires a parent page.",
                        node_name=self.get_definition().name,
                    )

                # Prepare page properties - match exact schema expected by API
                page_properties = {
                    "title": [
                        {"text": {"content": input_data.title}}
                    ]
                }

                # Build parent object
                parent = {"page_id": input_data.parent_page_id}

                # Notion MCP server uses "API-post-page" for creating pages
                page_tool = "API-post-page"

                # Verify tool exists
                available_tools = {t.name for t in connection.tools}
                if page_tool not in available_tools:
                    logger.warning(
                        "notion_page_tool_not_found",
                        expected_tool=page_tool,
                        available_tools=list(available_tools),
                    )
                    raise NodeExecutionError(
                        f"Notion MCP tool '{page_tool}' not found. Available: {available_tools}",
                        node_name=self.get_definition().name,
                    )

                logger.info("notion_calling_tool", tool_name=page_tool)

                # Build request with children if content is provided
                request_data = {
                    "parent": parent,
                    "properties": page_properties,
                }

                # Add content as children blocks if provided
                if input_data.content:
                    children = self._convert_content_to_blocks(input_data.content)
                    if children:
                        request_data["children"] = children
                        logger.info(
                            "notion_adding_content_blocks",
                            block_count=len(children),
                        )

                # Call Notion MCP tool
                result = await gateway.call_tool(connection, page_tool, request_data)

                # Parse response - result is dict with "content" list
                page_data = {}
                content = result.get("content", [])
                if content:
                    page_data = json.loads(content[0]["text"])

                return NotionCreatePageOutput(
                    success=True,
                    page_id=page_data.get("id", ""),
                    url=page_data.get("url", f"https://notion.so/{page_data.get('id', '')}"),
                    title=input_data.title,
                )

        except Exception as e:
            raise NodeExecutionError(
                f"Failed to create Notion page: {str(e)}",
                node_name=self.get_definition().name,
                details={"title": input_data.title},
            ) from e


@dataclass
class NotionSearchInput:
    """Input for searching Notion."""

    query: str
    filter_type: str | None = None  # "page", "database", etc.


@dataclass
class NotionSearchOutput:
    """Output from Notion search."""

    results: list[dict[str, Any]]
    total_count: int


class NotionSearchNode(BaseNode[NotionSearchInput, NotionSearchOutput]):
    """Notion MCP node for searching."""

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
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
                    required=True,
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
        )

    async def execute(
        self,
        input_data: NotionSearchInput,
        context: NodeContext,
    ) -> NotionSearchOutput:
        """Execute node."""
        import structlog
        logger = structlog.get_logger()

        if "notion_oauth" not in context.credentials:
            raise NodeValidationError("Missing required credential: notion_oauth")

        # Import gateway here to avoid circular dependency
        from src.services.mcp_gateway import MCPGateway

        # Get Notion credentials
        notion_creds = context.credentials["notion_oauth"]

        # Connect to Notion MCP server using context manager for proper cleanup
        gateway = MCPGateway()

        try:
            async with gateway.connection("notion", notion_creds) as connection:
                # Log available tools for debugging
                logger.info(
                    "notion_search_mcp_connected",
                    tool_count=len(connection.tools),
                    tools=[t.name for t in connection.tools],
                )

                # Notion MCP server uses "API-post-search" for searching
                search_tool = "API-post-search"

                # Verify tool exists
                available_tools = {t.name for t in connection.tools}
                if search_tool not in available_tools:
                    logger.warning(
                        "notion_search_tool_not_found",
                        expected_tool=search_tool,
                        available_tools=list(available_tools),
                    )
                    raise NodeExecutionError(
                        f"Notion MCP tool '{search_tool}' not found. Available: {available_tools}",
                        node_name=self.get_definition().name,
                    )

                # Prepare search request
                search_params: dict[str, Any] = {
                    "query": input_data.query,
                }

                # Add filter if specified
                if input_data.filter_type:
                    search_params["filter"] = {
                        "value": input_data.filter_type,
                        "property": "object",
                    }

                logger.info("notion_calling_search_tool", tool_name=search_tool)

                # Call Notion MCP search tool
                result = await gateway.call_tool(
                    connection,
                    search_tool,
                    search_params,
                )

                # Parse response - result is dict with "content" list
                import json
                search_data = {}
                content = result.get("content", [])
                if content:
                    search_data = json.loads(content[0]["text"])

                results = search_data.get("results", [])

                return NotionSearchOutput(
                    results=results,
                    total_count=len(results),
                )

        except Exception as e:
            raise NodeExecutionError(
                f"Failed to search Notion: {str(e)}",
                node_name=self.get_definition().name,
                details={"query": input_data.query},
            ) from e
