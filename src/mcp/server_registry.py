"""MCP Server Registry.

Maintains configuration for available MCP servers in the federated architecture.
"""

from dataclasses import dataclass, field
from typing import Literal


TransportType = Literal["stdio", "streamable_http", "sse"]


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server.

    Supports multiple transport types:
    - stdio: Local process communication (for CLI tools)
    - streamable_http: HTTP with streaming (for remote servers)
    - sse: Server-Sent Events (for real-time updates)
    """

    id: str
    name: str
    transport: TransportType
    credential_type: str | None = None
    tools: list[str] = field(default_factory=list)

    # Transport-specific fields
    url: str | None = None  # For HTTP/SSE
    command: str | None = None  # For stdio
    args: list[str] | None = None  # For stdio
    env: dict[str, str] | None = None  # For stdio

    # Optional metadata
    description: str | None = None
    icon: str | None = None
    version: str = "1.0.0"
    enabled: bool = True


class MCPServerRegistry:
    """Registry of available MCP servers.

    Federated architecture - each integration has its own MCP server.

    Example usage:
        registry = MCPServerRegistry()
        slack_config = registry.get("slack")
        available = registry.list_available(["slack_oauth", "github_token"])
    """

    def __init__(self) -> None:
        """Initialize registry with default servers."""
        self.servers: dict[str, MCPServerConfig] = self._get_default_servers()

    def _get_default_servers(self) -> dict[str, MCPServerConfig]:
        """Get default MCP server configurations."""
        return {
            "slack": MCPServerConfig(
                id="slack",
                name="Slack MCP",
                description="Slack messaging and workspace integration",
                transport="streamable_http",
                url="https://mcp.slack.com/v1",
                credential_type="slack_oauth",
                tools=[
                    "send_message",
                    "list_channels",
                    "search_messages",
                    "get_channel_info",
                    "list_users",
                ],
                icon="slack",
            ),
            "github": MCPServerConfig(
                id="github",
                name="GitHub MCP",
                description="GitHub repository and issue management",
                transport="streamable_http",
                url="https://gitmcp.io/api",
                credential_type="github_token",
                tools=[
                    "search_repos",
                    "create_issue",
                    "list_issues",
                    "create_pr",
                    "list_prs",
                    "get_file_contents",
                ],
                icon="github",
            ),
            "filesystem": MCPServerConfig(
                id="filesystem",
                name="Filesystem MCP",
                description="Local filesystem operations",
                transport="stdio",
                command="npx",
                args=["-y", "@anthropic/mcp-filesystem"],
                credential_type=None,  # No auth required
                tools=[
                    "read_file",
                    "write_file",
                    "list_directory",
                    "create_directory",
                    "delete_file",
                ],
                icon="folder",
            ),
            "google_drive": MCPServerConfig(
                id="google_drive",
                name="Google Drive MCP",
                description="Google Drive file management",
                transport="streamable_http",
                url="https://mcp.googleapis.com/drive/v1",
                credential_type="google_oauth",
                tools=[
                    "list_files",
                    "get_file",
                    "create_file",
                    "update_file",
                    "delete_file",
                    "share_file",
                ],
                icon="google-drive",
                enabled=False,  # Not yet implemented
            ),
            "notion": MCPServerConfig(
                id="notion",
                name="Notion MCP",
                description="Notion workspace management via official MCP server",
                transport="stdio",
                command="npx",
                args=["-y", "@notionhq/notion-mcp-server"],
                credential_type="notion_oauth",
                tools=[
                    "v1/search",
                    "v1/pages",
                    "v1/pages/[page_id]",
                    "v1/blocks/[block_id]/children",
                    "v1/comments",
                    "v1/databases/[database_id]/query",
                ],
                icon="notion",
                enabled=True,
            ),
        }

    def get(self, server_id: str) -> MCPServerConfig | None:
        """Get server configuration by ID.

        Args:
            server_id: Server identifier

        Returns:
            Server configuration or None
        """
        server = self.servers.get(server_id)
        if server and server.enabled:
            return server
        return None

    def list_all(self) -> list[MCPServerConfig]:
        """List all server configurations.

        Returns:
            List of all servers (including disabled)
        """
        return list(self.servers.values())

    def list_enabled(self) -> list[MCPServerConfig]:
        """List enabled server configurations.

        Returns:
            List of enabled servers
        """
        return [s for s in self.servers.values() if s.enabled]

    def list_available(
        self,
        available_credentials: list[str],
    ) -> list[MCPServerConfig]:
        """List servers available to a user.

        Args:
            available_credentials: Credential types the user has

        Returns:
            List of accessible servers
        """
        result = []
        for server in self.servers.values():
            if not server.enabled:
                continue
            if server.credential_type is None:
                # No auth required
                result.append(server)
            elif server.credential_type in available_credentials:
                # User has required credential
                result.append(server)
        return result

    def list_by_transport(
        self,
        transport: TransportType,
    ) -> list[MCPServerConfig]:
        """List servers by transport type.

        Args:
            transport: Transport type

        Returns:
            List of matching servers
        """
        return [
            s for s in self.servers.values()
            if s.transport == transport and s.enabled
        ]

    def register(self, config: MCPServerConfig) -> None:
        """Register a new MCP server.

        Args:
            config: Server configuration
        """
        self.servers[config.id] = config

    def unregister(self, server_id: str) -> None:
        """Remove an MCP server.

        Args:
            server_id: Server identifier
        """
        self.servers.pop(server_id, None)

    def enable(self, server_id: str) -> bool:
        """Enable an MCP server.

        Args:
            server_id: Server identifier

        Returns:
            True if server was enabled
        """
        server = self.servers.get(server_id)
        if server:
            server.enabled = True
            return True
        return False

    def disable(self, server_id: str) -> bool:
        """Disable an MCP server.

        Args:
            server_id: Server identifier

        Returns:
            True if server was disabled
        """
        server = self.servers.get(server_id)
        if server:
            server.enabled = False
            return True
        return False
