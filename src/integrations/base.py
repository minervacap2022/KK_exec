"""Base classes for integrations.

Defines the interface that all integrations must implement.
"""

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


@dataclass
class OAuthConfig:
    """OAuth configuration for an integration."""

    provider_id: str
    display_name: str
    client_id: str | None
    client_secret: str | None
    redirect_uri: str
    authorize_url: str
    token_url: str
    scopes: list[str]
    credential_type: str
    mcp_server_id: str | None


@dataclass
class OAuthTokens:
    """OAuth tokens returned from token exchange."""

    access_token: str
    token_type: str = "Bearer"
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scope: str | None = None
    raw_response: dict[str, Any] | None = None


class BaseIntegration(ABC):
    """Base class for all integrations.

    Each integration must implement:
    - get_oauth_config(): Return OAuth configuration
    - build_authorization_params(): Build provider-specific auth params
    - exchange_code(): Exchange authorization code for tokens
    - build_credential_data(): Build credential data from tokens
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider identifier (e.g., 'slack', 'github', 'notion')."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable provider name."""
        ...

    @abstractmethod
    def get_oauth_config(self) -> OAuthConfig:
        """Get OAuth configuration for this provider."""
        ...

    @abstractmethod
    def build_authorization_params(
        self,
        config: OAuthConfig,
        state: str,
        extra_scopes: list[str] | None = None,
    ) -> dict[str, str]:
        """Build provider-specific authorization URL parameters."""
        ...

    @abstractmethod
    async def exchange_code(
        self,
        client: httpx.AsyncClient,
        config: OAuthConfig,
        code: str,
    ) -> OAuthTokens:
        """Exchange authorization code for tokens."""
        ...

    @abstractmethod
    def build_credential_data(
        self,
        tokens: OAuthTokens,
    ) -> dict[str, Any]:
        """Build credential data from OAuth tokens."""
        ...

    def is_configured(self) -> bool:
        """Check if the integration is properly configured."""
        config = self.get_oauth_config()
        return bool(config.client_id and config.client_secret)

    @staticmethod
    def build_basic_auth_header(client_id: str, client_secret: str) -> str:
        """Build HTTP Basic Auth header value."""
        credentials = f"{client_id}:{client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"
