"""API route handlers."""

from src.api.routes.auth import router as auth_router
from src.api.routes.credentials import router as credentials_router
from src.api.routes.executions import router as executions_router
from src.api.routes.mcp import router as mcp_router
from src.api.routes.nodes import router as nodes_router
from src.api.routes.oauth import router as oauth_router
from src.api.routes.workflows import router as workflows_router

__all__ = [
    "auth_router",
    "credentials_router",
    "executions_router",
    "mcp_router",
    "nodes_router",
    "oauth_router",
    "workflows_router",
]
