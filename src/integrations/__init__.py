"""Integrations module.

Each integration (Slack, GitHub, Notion, etc.) has its own folder with:
- oauth.py: OAuth provider configuration and token exchange
- config.py: Integration-specific configuration
- __init__.py: Exports

This structure makes it easy to add new integrations.
"""

from src.integrations.registry import IntegrationRegistry, get_integration_registry

__all__ = [
    "IntegrationRegistry",
    "get_integration_registry",
]
