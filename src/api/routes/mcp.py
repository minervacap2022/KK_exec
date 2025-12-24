"""MCP server API endpoints.

Provides access to federated MCP servers and their tools.
"""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from src.api.deps import CredentialServiceDep, CurrentUser, MCPGatewayDep, OptionalUser
from src.services.mcp_gateway import (
    MCPConnectionError,
    MCPServerNotFoundError,
)

logger = structlog.get_logger()

router = APIRouter()


@router.get("/servers", response_model=list[dict[str, Any]])
async def list_servers(
    user: OptionalUser,
    gateway: MCPGatewayDep,
    credential_service: CredentialServiceDep,
) -> list[dict[str, Any]]:
    """List available MCP servers.

    If authenticated, includes availability based on user's credentials.

    Args:
        user: Current user (optional)
        gateway: MCP gateway
        credential_service: Credential service

    Returns:
        List of MCP server configurations
    """
    servers = gateway.list_servers()

    result = []
    available_credentials = []

    if user is not None:
        available_credentials = await credential_service.get_available_types(user.id)

    for server in servers:
        server_dict = {
            "id": server.id,
            "name": server.name,
            "transport": server.transport,
            "credential_type": server.credential_type,
            "tools": server.tools,
        }

        # Add availability info
        if server.credential_type is None:
            server_dict["available"] = True
        else:
            server_dict["available"] = server.credential_type in available_credentials

        result.append(server_dict)

    return result


@router.get("/servers/{server_id}", response_model=dict[str, Any])
async def get_server(
    server_id: str,
    user: OptionalUser,
    gateway: MCPGatewayDep,
    credential_service: CredentialServiceDep,
) -> dict[str, Any]:
    """Get MCP server details.

    Args:
        server_id: Server identifier
        user: Current user (optional)
        gateway: MCP gateway
        credential_service: Credential service

    Returns:
        Server configuration
    """
    server = gateway.get_server(server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{server_id}' not found",
        )

    result = {
        "id": server.id,
        "name": server.name,
        "transport": server.transport,
        "credential_type": server.credential_type,
        "tools": server.tools,
        "url": server.url,
    }

    # Add availability info
    if user is not None:
        available_credentials = await credential_service.get_available_types(user.id)
        result["available"] = (
            server.credential_type is None
            or server.credential_type in available_credentials
        )
    else:
        result["available"] = server.credential_type is None

    return result


@router.get("/servers/{server_id}/tools", response_model=list[dict[str, Any]])
async def list_server_tools(
    server_id: str,
    user: CurrentUser,
    gateway: MCPGatewayDep,
    credential_service: CredentialServiceDep,
) -> list[dict[str, Any]]:
    """List tools available on an MCP server.

    Requires authentication. Will use user's credentials to connect
    if the server requires authentication.

    Args:
        server_id: Server identifier
        user: Current authenticated user
        gateway: MCP gateway
        credential_service: Credential service

    Returns:
        List of tool definitions
    """
    server = gateway.get_server(server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{server_id}' not found",
        )

    # Get user credential for this server
    user_creds = None
    if server.credential_type:
        credential = await credential_service.get_for_mcp_server(user.id, server_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No credential configured for MCP server '{server_id}'",
            )
        user_creds = credential.data

    try:
        tools = await gateway.list_tools(server_id, user_creds)
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
    except MCPConnectionError as e:
        logger.error(
            "mcp_tools_fetch_failed",
            server_id=server_id,
            user_id=user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to MCP server: {str(e)}",
        ) from e


@router.post("/servers/{server_id}/connect", response_model=dict[str, Any])
async def connect_to_server(
    server_id: str,
    user: CurrentUser,
    gateway: MCPGatewayDep,
    credential_service: CredentialServiceDep,
) -> dict[str, Any]:
    """Test connection to an MCP server.

    Args:
        server_id: Server identifier
        user: Current authenticated user
        gateway: MCP gateway
        credential_service: Credential service

    Returns:
        Connection status and available tools
    """
    server = gateway.get_server(server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{server_id}' not found",
        )

    # Get user credential
    user_creds = None
    if server.credential_type:
        credential = await credential_service.get_for_mcp_server(user.id, server_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No credential configured for MCP server '{server_id}'",
            )
        user_creds = credential.data

    try:
        connection = await gateway.connect(server_id, user_creds)
        return {
            "status": "connected",
            "server_id": server_id,
            "server_name": server.name,
            "tool_count": len(connection.tools),
            "tools": [t.name for t in connection.tools],
        }
    except MCPConnectionError as e:
        logger.error(
            "mcp_connection_failed",
            server_id=server_id,
            user_id=user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect: {str(e)}",
        ) from e


@router.get("/available", response_model=list[dict[str, Any]])
async def list_available_servers(
    user: CurrentUser,
    gateway: MCPGatewayDep,
    credential_service: CredentialServiceDep,
) -> list[dict[str, Any]]:
    """List MCP servers available to the current user.

    Only returns servers the user has credentials for (or don't require auth).

    Args:
        user: Current authenticated user
        gateway: MCP gateway
        credential_service: Credential service

    Returns:
        List of available servers
    """
    available_credentials = await credential_service.get_available_types(user.id)
    servers = gateway.get_servers_available_to_user(available_credentials)

    return [
        {
            "id": s.id,
            "name": s.name,
            "transport": s.transport,
            "credential_type": s.credential_type,
            "tools": s.tools,
            "available": True,
        }
        for s in servers
    ]
