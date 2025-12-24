"""MCP Transport Adapters.

Provides transport implementations for different MCP connection types.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


class MCPTransportError(Exception):
    """Error in MCP transport operations."""

    pass


class MCPConnectionError(MCPTransportError):
    """Failed to connect to MCP server."""

    pass


class MCPTimeoutError(MCPTransportError):
    """MCP operation timed out."""

    pass


@dataclass
class MCPMessage:
    """Message for MCP communication."""

    method: str
    params: dict[str, Any] | None = None
    id: str | None = None


@dataclass
class MCPResponse:
    """Response from MCP server."""

    result: Any = None
    error: dict[str, Any] | None = None
    id: str | None = None


class MCPTransport(ABC):
    """Abstract base class for MCP transports.

    Implements the transport layer for MCP communication.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to MCP server.

        Raises:
            MCPConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to MCP server."""
        pass

    @abstractmethod
    async def send(self, message: MCPMessage) -> MCPResponse:
        """Send message and wait for response.

        Args:
            message: Message to send

        Returns:
            Server response

        Raises:
            MCPTransportError: If send fails
        """
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        pass


class StdioTransport(MCPTransport):
    """Transport for stdio-based MCP servers.

    Communicates with local MCP processes via stdin/stdout.
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> None:
        """Initialize stdio transport.

        Args:
            command: Command to execute
            args: Command arguments
            env: Environment variables
            timeout: Operation timeout in seconds
        """
        self.command = command
        self.args = args or []
        self.env = env
        self.timeout = timeout
        self._process = None
        self._connected = False

    async def connect(self) -> None:
        """Start the MCP server process."""
        import asyncio

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )
            self._connected = True
            logger.info(
                "stdio_transport_connected",
                command=self.command,
                pid=self._process.pid,
            )
        except Exception as e:
            raise MCPConnectionError(f"Failed to start process: {str(e)}") from e

    async def disconnect(self) -> None:
        """Terminate the MCP server process."""
        if self._process:
            self._process.terminate()
            await self._process.wait()
            self._connected = False
            logger.info("stdio_transport_disconnected")

    async def send(self, message: MCPMessage) -> MCPResponse:
        """Send message via stdin and receive response via stdout."""
        import asyncio
        import json

        if not self._connected or not self._process:
            raise MCPConnectionError("Not connected")

        try:
            # Encode message as JSON-RPC
            json_message = json.dumps({
                "jsonrpc": "2.0",
                "method": message.method,
                "params": message.params or {},
                "id": message.id or "1",
            })

            # Send to stdin
            self._process.stdin.write((json_message + "\n").encode())
            await self._process.stdin.drain()

            # Read from stdout
            response_line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self.timeout,
            )

            response_data = json.loads(response_line.decode())

            return MCPResponse(
                result=response_data.get("result"),
                error=response_data.get("error"),
                id=response_data.get("id"),
            )

        except asyncio.TimeoutError as e:
            raise MCPTimeoutError("Operation timed out") from e
        except Exception as e:
            raise MCPTransportError(f"Send failed: {str(e)}") from e

    @property
    def is_connected(self) -> bool:
        """Check if process is running."""
        return self._connected and self._process and self._process.returncode is None


class StreamableHttpTransport(MCPTransport):
    """Transport for streamable HTTP-based MCP servers.

    Communicates with remote MCP servers via HTTP with streaming support.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> None:
        """Initialize HTTP transport.

        Args:
            url: Server URL
            headers: HTTP headers (for auth)
            timeout: Request timeout in seconds
        """
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._client = None
        self._connected = False

    async def connect(self) -> None:
        """Initialize HTTP client."""
        import httpx

        self._client = httpx.AsyncClient(
            base_url=self.url,
            headers=self.headers,
            timeout=self.timeout,
        )
        self._connected = True
        logger.info("http_transport_connected", url=self.url)

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._connected = False
            logger.info("http_transport_disconnected")

    async def send(self, message: MCPMessage) -> MCPResponse:
        """Send message via HTTP POST."""
        import json

        if not self._connected or not self._client:
            raise MCPConnectionError("Not connected")

        try:
            response = await self._client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": message.method,
                    "params": message.params or {},
                    "id": message.id or "1",
                },
            )
            response.raise_for_status()
            data = response.json()

            return MCPResponse(
                result=data.get("result"),
                error=data.get("error"),
                id=data.get("id"),
            )

        except Exception as e:
            raise MCPTransportError(f"HTTP request failed: {str(e)}") from e

    @property
    def is_connected(self) -> bool:
        """Check if client is initialized."""
        return self._connected and self._client is not None


class SSETransport(MCPTransport):
    """Transport for SSE-based MCP servers.

    Communicates with MCP servers using Server-Sent Events.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> None:
        """Initialize SSE transport.

        Args:
            url: Server URL
            headers: HTTP headers (for auth)
            timeout: Connection timeout in seconds
        """
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._connected = False
        self._client = None

    async def connect(self) -> None:
        """Initialize SSE connection."""
        import httpx

        self._client = httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
        )
        self._connected = True
        logger.info("sse_transport_connected", url=self.url)

    async def disconnect(self) -> None:
        """Close SSE connection."""
        if self._client:
            await self._client.aclose()
            self._connected = False
            logger.info("sse_transport_disconnected")

    async def send(self, message: MCPMessage) -> MCPResponse:
        """Send message and receive SSE response."""
        if not self._connected or not self._client:
            raise MCPConnectionError("Not connected")

        try:
            # For SSE, we POST a request and stream the response
            async with self._client.stream(
                "POST",
                f"{self.url}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": message.method,
                    "params": message.params or {},
                    "id": message.id or "1",
                },
            ) as response:
                response.raise_for_status()

                # Collect SSE events
                result = None
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        data = json.loads(line[6:])
                        if "result" in data or "error" in data:
                            result = data
                            break

                if result:
                    return MCPResponse(
                        result=result.get("result"),
                        error=result.get("error"),
                        id=result.get("id"),
                    )
                raise MCPTransportError("No response received")

        except Exception as e:
            raise MCPTransportError(f"SSE request failed: {str(e)}") from e

    @property
    def is_connected(self) -> bool:
        """Check if client is initialized."""
        return self._connected and self._client is not None


def create_transport(
    transport_type: str,
    **kwargs: Any,
) -> MCPTransport:
    """Factory function to create appropriate transport.

    Args:
        transport_type: Type of transport (stdio, streamable_http, sse)
        **kwargs: Transport-specific arguments

    Returns:
        Configured transport instance

    Raises:
        ValueError: If transport type is unknown
    """
    if transport_type == "stdio":
        return StdioTransport(
            command=kwargs["command"],
            args=kwargs.get("args"),
            env=kwargs.get("env"),
            timeout=kwargs.get("timeout", 30),
        )
    elif transport_type == "streamable_http":
        return StreamableHttpTransport(
            url=kwargs["url"],
            headers=kwargs.get("headers"),
            timeout=kwargs.get("timeout", 30),
        )
    elif transport_type == "sse":
        return SSETransport(
            url=kwargs["url"],
            headers=kwargs.get("headers"),
            timeout=kwargs.get("timeout", 30),
        )
    else:
        raise ValueError(f"Unknown transport type: {transport_type}")
