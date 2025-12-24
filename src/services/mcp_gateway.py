"""MCP Gateway service.

Manages federated MCP server connections with user-specific credentials.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from subprocess import PIPE
from typing import Any, AsyncGenerator

import structlog
from mcp import ClientSession
from mcp.client.sse import sse_client

from src.models.credential import CredentialDecrypted
from src.mcp.server_registry import MCPServerConfig, MCPServerRegistry

logger = structlog.get_logger()


class MCPGatewayError(Exception):
    """Error in MCP gateway operations."""

    pass


class MCPServerNotFoundError(MCPGatewayError):
    """MCP server not found."""

    pass


class MCPConnectionError(MCPGatewayError):
    """Failed to connect to MCP server."""

    pass


class MCPToolError(MCPGatewayError):
    """Error executing MCP tool."""

    pass


class _SubprocessMCPConnection:
    """Low-level MCP connection using subprocess.

    This avoids issues with the MCP library's anyio-based stdio_client
    by using direct subprocess communication.
    """

    def __init__(self, proc: asyncio.subprocess.Process):
        self._proc = proc
        self._request_id = 0
        self._lock = asyncio.Lock()

    async def _send_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send JSON-RPC request and wait for response."""
        async with self._lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params or {},
            }

            if self._proc.stdin is None or self._proc.stdout is None:
                raise MCPConnectionError("Subprocess stdin/stdout not available")

            # Send request
            request_bytes = json.dumps(request).encode() + b"\n"
            self._proc.stdin.write(request_bytes)
            await self._proc.stdin.drain()

            # Read response
            response_line = await asyncio.wait_for(
                self._proc.stdout.readline(),
                timeout=60.0,
            )

            if not response_line:
                # Check for stderr output
                if self._proc.stderr:
                    stderr = await self._proc.stderr.read(1000)
                    if stderr:
                        raise MCPConnectionError(f"MCP server error: {stderr.decode()}")
                raise MCPConnectionError("MCP server closed connection")

            response = json.loads(response_line.decode())

            if "error" in response:
                error = response["error"]
                raise MCPToolError(f"MCP error: {error.get('message', str(error))}")

            return response.get("result")

    async def initialize(self) -> dict[str, Any]:
        """Initialize MCP session."""
        result = await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kk_exec", "version": "1.0.0"},
            },
        )
        return dict(result) if result else {}

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools."""
        result = await self._send_request("tools/list")
        tools: list[dict[str, Any]] = result.get("tools", []) if result else []
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool."""
        return await self._send_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )


@dataclass
class MCPToolInfo:
    """Information about an MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class MCPServerConnection:
    """Active connection to an MCP server."""

    server_id: str
    config: MCPServerConfig
    session: ClientSession | None = None
    tools: list[MCPToolInfo] = field(default_factory=list)


class MCPGateway:
    """Gateway for federated MCP server management.

    Handles:
    - Server discovery and registration
    - User-scoped credential injection
    - Tool listing and execution
    - Connection lifecycle management

    Example usage:
        gateway = MCPGateway()

        # List available servers
        servers = gateway.list_servers()

        # Connect with user credentials using context manager
        async with gateway.connection("notion", user_credentials) as conn:
            tools = conn.tools
            result = await gateway.call_tool(conn, "notion-create-pages", {...})
    """

    def __init__(self) -> None:
        """Initialize MCP gateway."""
        self._registry = MCPServerRegistry()

    def list_servers(self) -> list[MCPServerConfig]:
        """List all available MCP servers.

        Returns:
            List of server configurations
        """
        return list(self._registry.servers.values())

    def get_server(self, server_id: str) -> MCPServerConfig | None:
        """Get server configuration by ID.

        Args:
            server_id: Server identifier

        Returns:
            Server configuration or None
        """
        return self._registry.servers.get(server_id)

    @asynccontextmanager
    async def connection(
        self,
        server_id: str,
        user_credentials: dict[str, Any] | None = None,
    ) -> AsyncGenerator[MCPServerConnection, None]:
        """Context manager for MCP server connections.

        This ensures proper cleanup of anyio task groups and cancel scopes
        by keeping the connection lifecycle within a single async context.

        Args:
            server_id: Server identifier
            user_credentials: User-specific credentials for the server

        Yields:
            Active server connection

        Raises:
            MCPServerNotFoundError: If server doesn't exist
            MCPConnectionError: If connection fails

        Example:
            async with gateway.connection("notion", creds) as conn:
                result = await gateway.call_tool(conn, "notion-search", {"query": "test"})
        """
        config = self._registry.servers.get(server_id)
        if config is None:
            raise MCPServerNotFoundError(f"MCP server '{server_id}' not found")

        try:
            # Connect based on transport type using proper async with
            if config.transport == "stdio":
                async with self._stdio_connection(config, user_credentials) as conn:
                    yield conn
            elif config.transport == "streamable_http":
                async with self._http_connection(config, user_credentials) as conn:
                    yield conn
            elif config.transport == "sse":
                async with self._sse_connection(config, user_credentials) as conn:
                    yield conn
            else:
                raise MCPConnectionError(f"Unsupported transport: {config.transport}")

        except MCPGatewayError:
            raise
        except Exception as e:
            logger.error(
                "mcp_connection_failed",
                server_id=server_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            raise MCPConnectionError(f"Failed to connect to {server_id}: {str(e)}") from e

    @asynccontextmanager
    async def _stdio_connection(
        self,
        config: MCPServerConfig,
        credentials: dict[str, Any] | None = None,
    ) -> AsyncGenerator[MCPServerConnection, None]:
        """Create a stdio MCP connection using subprocess.

        Uses asyncio.create_subprocess_exec instead of the MCP library's
        stdio_client to avoid anyio task group issues.
        """
        if not config.command:
            raise MCPConnectionError("Stdio transport requires 'command'")

        # Prepare environment variables - must include full PATH for npx
        env = os.environ.copy()
        if config.env:
            env.update(config.env)

        # Inject user credentials as environment variables
        if credentials:
            if config.id == "notion" and "access_token" in credentials:
                env["NOTION_TOKEN"] = credentials["access_token"]
            elif "token" in credentials:
                env["MCP_TOKEN"] = credentials["token"]
            elif "api_key" in credentials:
                env["MCP_API_KEY"] = credentials["api_key"]

        # Build command args
        cmd = [config.command] + (config.args or [])

        # Start subprocess
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            env=env,
        )

        try:
            # Create subprocess-based connection wrapper
            subprocess_conn = _SubprocessMCPConnection(proc)

            # Initialize MCP session
            await subprocess_conn.initialize()

            # Get available tools
            tools_response = await subprocess_conn.list_tools()
            tools = [
                MCPToolInfo(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    input_schema=tool.get("inputSchema", {}),
                )
                for tool in tools_response
            ]

            connection = MCPServerConnection(
                server_id=config.id,
                config=config,
                session=None,  # Not using ClientSession
                tools=tools,
            )
            # Store subprocess connection for tool calls
            connection._subprocess_conn = subprocess_conn  # type: ignore

            logger.info(
                "mcp_server_connected",
                server_id=config.id,
                transport=config.transport,
                tool_count=len(tools),
            )

            yield connection

            logger.info("mcp_server_disconnected", server_id=config.id)

        finally:
            # Clean up subprocess
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()

    @asynccontextmanager
    async def _http_connection(
        self,
        config: MCPServerConfig,
        credentials: dict[str, Any] | None,
    ) -> AsyncGenerator[MCPServerConnection, None]:
        """Create an HTTP MCP connection with proper lifecycle management."""
        if not config.url:
            raise MCPConnectionError("HTTP transport requires 'url'")

        headers = {}
        if credentials:
            if "access_token" in credentials:
                headers["Authorization"] = f"Bearer {credentials['access_token']}"
            elif "token" in credentials:
                headers["Authorization"] = f"Bearer {credentials['token']}"
            elif "api_key" in credentials:
                headers["X-API-Key"] = credentials["api_key"]

        async with sse_client(config.url, headers=headers) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            await session.initialize()

            tools_response = await session.list_tools()
            tools = [
                MCPToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema or {},
                )
                for tool in tools_response.tools
            ]

            connection = MCPServerConnection(
                server_id=config.id,
                config=config,
                session=session,
                tools=tools,
            )

            logger.info(
                "mcp_server_connected",
                server_id=config.id,
                transport=config.transport,
                tool_count=len(tools),
            )

            yield connection

            logger.info("mcp_server_disconnected", server_id=config.id)

    @asynccontextmanager
    async def _sse_connection(
        self,
        config: MCPServerConfig,
        credentials: dict[str, Any] | None,
    ) -> AsyncGenerator[MCPServerConnection, None]:
        """Create an SSE MCP connection with proper lifecycle management."""
        if not config.url:
            raise MCPConnectionError("SSE transport requires 'url'")

        headers = {}
        if credentials:
            if "access_token" in credentials:
                headers["Authorization"] = f"Bearer {credentials['access_token']}"
            elif "token" in credentials:
                headers["Authorization"] = f"Bearer {credentials['token']}"

        async with sse_client(config.url, headers=headers) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            await session.initialize()

            tools_response = await session.list_tools()
            tools = [
                MCPToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema or {},
                )
                for tool in tools_response.tools
            ]

            connection = MCPServerConnection(
                server_id=config.id,
                config=config,
                session=session,
                tools=tools,
            )

            logger.info(
                "mcp_server_connected",
                server_id=config.id,
                transport=config.transport,
                tool_count=len(tools),
            )

            yield connection

            logger.info("mcp_server_disconnected", server_id=config.id)

    async def call_tool(
        self,
        connection: MCPServerConnection,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Call a tool on an MCP server.

        Args:
            connection: Active server connection
            tool_name: Tool to call
            arguments: Tool arguments

        Returns:
            Tool result

        Raises:
            MCPToolError: If tool execution fails
        """
        try:
            # Check for subprocess-based connection (stdio)
            subprocess_conn = getattr(connection, "_subprocess_conn", None)
            if subprocess_conn is not None:
                result = await subprocess_conn.call_tool(tool_name, arguments)
            elif connection.session is not None:
                # Use ClientSession for HTTP/SSE connections
                result = await connection.session.call_tool(tool_name, arguments)
            else:
                raise MCPToolError("Connection has no active session or subprocess")

            logger.debug(
                "mcp_tool_called",
                server_id=connection.server_id,
                tool_name=tool_name,
            )

            return result

        except MCPToolError:
            raise
        except Exception as e:
            logger.error(
                "mcp_tool_failed",
                server_id=connection.server_id,
                tool_name=tool_name,
                error_type=type(e).__name__,
                error=str(e),
            )
            raise MCPToolError(f"Tool '{tool_name}' failed: {str(e)}") from e

    async def get_server_tools_for_user(
        self,
        server_id: str,
        credential: CredentialDecrypted | None,
    ) -> list[MCPToolInfo]:
        """Get tools available to a user for a specific server.

        Args:
            server_id: Server identifier
            credential: User's decrypted credential for the server

        Returns:
            List of available tools
        """
        config = self.get_server(server_id)
        if config is None:
            return []

        # If server requires auth and user has no credential, return empty
        if config.credential_type and credential is None:
            return []

        try:
            user_creds = credential.data if credential else None
            async with self.connection(server_id, user_creds) as conn:
                return conn.tools
        except MCPConnectionError:
            logger.warning(
                "mcp_server_unavailable",
                server_id=server_id,
            )
            return []

    def get_servers_by_credential_type(
        self,
        credential_type: str,
    ) -> list[MCPServerConfig]:
        """Get servers that use a specific credential type.

        Args:
            credential_type: Credential type identifier

        Returns:
            List of matching servers
        """
        return [
            s for s in self._registry.servers.values()
            if s.credential_type == credential_type
        ]

    def get_servers_available_to_user(
        self,
        available_credentials: list[str],
    ) -> list[MCPServerConfig]:
        """Get servers available to a user based on their credentials.

        Args:
            available_credentials: List of credential types the user has

        Returns:
            List of accessible servers
        """
        result = []
        for server in self._registry.servers.values():
            if server.credential_type is None:
                # No auth required
                result.append(server)
            elif server.credential_type in available_credentials:
                # User has required credential
                result.append(server)
        return result
