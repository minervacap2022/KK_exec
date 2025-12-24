"""Node library API endpoints.

Provides access to available workflow nodes.
"""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from src.api.deps import CredentialServiceDep, CurrentUser, OptionalUser
from src.models.node import NodeCategory
from src.services.node_library import get_node_library

logger = structlog.get_logger()

router = APIRouter()


@router.get("", response_model=dict[str, Any])
async def list_nodes(
    user: OptionalUser,
    credential_service: CredentialServiceDep,
) -> dict[str, Any]:
    """List all available nodes.

    Returns nodes organized by category. If authenticated,
    also indicates which nodes are available based on user's credentials.

    Args:
        user: Current user (optional)
        credential_service: Credential service

    Returns:
        Node catalog with categories
    """
    library = get_node_library()
    catalog = library.get_catalog()

    # Add availability info if user is authenticated
    if user is not None:
        available_credentials = await credential_service.get_available_types(user.id)

        # Add 'available' flag to each node
        for category_nodes in catalog["categories"].values():
            for node in category_nodes:
                cred_type = node.get("credential_type")
                node["available"] = (
                    cred_type is None or cred_type in available_credentials
                )
    else:
        # Mark all nodes as available (for unauthenticated browsing)
        for category_nodes in catalog["categories"].values():
            for node in category_nodes:
                node["available"] = node.get("credential_type") is None

    return catalog


@router.get("/category/{category}", response_model=list[dict[str, Any]])
async def list_nodes_by_category(
    category: NodeCategory,
    user: OptionalUser,
    credential_service: CredentialServiceDep,
) -> list[dict[str, Any]]:
    """List nodes by category.

    Args:
        category: Node category (tool, api, mcp)
        user: Current user (optional)
        credential_service: Credential service

    Returns:
        List of nodes in the category
    """
    library = get_node_library()
    nodes = library.get_nodes_by_category(category)

    result = [n.to_dict() for n in nodes]

    # Add availability info if user is authenticated
    if user is not None:
        available_credentials = await credential_service.get_available_types(user.id)
        for node in result:
            cred_type = node.get("credential_type")
            node["available"] = cred_type is None or cred_type in available_credentials
    else:
        for node in result:
            node["available"] = node.get("credential_type") is None

    return result


@router.get("/available", response_model=list[dict[str, Any]])
async def list_available_nodes(
    user: CurrentUser,
    credential_service: CredentialServiceDep,
) -> list[dict[str, Any]]:
    """List nodes available to the current user.

    Only returns nodes the user can actually use based on their credentials.

    Args:
        user: Current authenticated user
        credential_service: Credential service

    Returns:
        List of available nodes
    """
    available_credentials = await credential_service.get_available_types(user.id)

    library = get_node_library()
    nodes = library.get_available_nodes(available_credentials)

    return [n.to_dict() for n in nodes]


@router.get("/{node_name}", response_model=dict[str, Any])
async def get_node(
    node_name: str,
    user: OptionalUser,
    credential_service: CredentialServiceDep,
) -> dict[str, Any]:
    """Get a specific node by name.

    Args:
        node_name: Node identifier
        user: Current user (optional)
        credential_service: Credential service

    Returns:
        Node definition
    """
    library = get_node_library()
    node = library.get(node_name)

    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_name}' not found",
        )

    result = node.to_dict()

    # Add availability info if user is authenticated
    if user is not None:
        available_credentials = await credential_service.get_available_types(user.id)
        cred_type = node.credential_type
        result["available"] = cred_type is None or cred_type in available_credentials
    else:
        result["available"] = node.credential_type is None

    return result


@router.get("/mcp/{mcp_server_id}", response_model=list[dict[str, Any]])
async def list_nodes_for_mcp_server(
    mcp_server_id: str,
    user: OptionalUser,
    credential_service: CredentialServiceDep,
) -> list[dict[str, Any]]:
    """List nodes for a specific MCP server.

    Args:
        mcp_server_id: MCP server identifier
        user: Current user (optional)
        credential_service: Credential service

    Returns:
        List of nodes for the MCP server
    """
    library = get_node_library()
    nodes = library.get_nodes_for_mcp_server(mcp_server_id)

    if not nodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No nodes found for MCP server '{mcp_server_id}'",
        )

    result = [n.to_dict() for n in nodes]

    # Add availability info
    if user is not None:
        available_credentials = await credential_service.get_available_types(user.id)
        for node in result:
            cred_type = node.get("credential_type")
            node["available"] = cred_type is None or cred_type in available_credentials
    else:
        for node in result:
            node["available"] = node.get("credential_type") is None

    return result


@router.get("/search", response_model=list[dict[str, Any]])
async def search_nodes(
    query: Annotated[str, Query(min_length=1, max_length=100)],
    user: OptionalUser,
    credential_service: CredentialServiceDep,
    category: Annotated[NodeCategory | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, Any]]:
    """Search nodes by keyword.

    Args:
        query: Search query
        user: Current user (optional)
        credential_service: Credential service
        category: Filter by category
        limit: Maximum results

    Returns:
        Matching nodes
    """
    from src.core.node_selector import NodeSelector

    library = get_node_library()

    # Get available credentials if authenticated
    available_credentials = None
    if user is not None:
        available_credentials = await credential_service.get_available_types(user.id)

    # Use node selector for search
    selector = NodeSelector(library.get_all_nodes())
    result = selector.select(
        query=query,
        available_credentials=available_credentials,
        category_filter=category,
        max_results=limit,
    )

    nodes = []
    for match in result.matches:
        node_dict = match.node.to_dict()
        node_dict["match_confidence"] = match.confidence
        node_dict["match_reason"] = match.reason
        node_dict["available"] = True  # Only available nodes are returned
        nodes.append(node_dict)

    return nodes
