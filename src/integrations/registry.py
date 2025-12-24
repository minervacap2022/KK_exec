"""Integration registry.

Central registry for all OAuth integrations.
Automatically discovers and loads integrations from the integrations folder.
"""

from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from src.integrations.base import BaseIntegration, OAuthConfig, OAuthTokens
from src.integrations.github import GitHubIntegration
from src.integrations.notion import NotionIntegration
from src.integrations.slack import SlackIntegration

logger = structlog.get_logger()


class IntegrationNotFoundError(Exception):
    """Integration not found."""

    pass


class IntegrationNotConfiguredError(Exception):
    """Integration not configured (missing client_id/secret)."""

    pass


class IntegrationCodeExchangeError(Exception):
    """Failed to exchange authorization code for tokens."""

    pass


class IntegrationRegistry:
    """Registry for managing OAuth integrations.

    Provides:
    - Integration discovery and lookup
    - Authorization URL generation
    - Token exchange
    - Credential data building

    Example usage:
        registry = IntegrationRegistry()

        # Get authorization URL
        auth_url = registry.get_authorization_url("slack", state="abc123")

        # Exchange code for tokens
        tokens = await registry.exchange_code("slack", code="xyz789")

        # Build credential data
        cred_data = registry.build_credential_data("slack", tokens)
    """

    def __init__(self) -> None:
        """Initialize registry with all known integrations."""
        self._integrations: dict[str, BaseIntegration] = {}
        self._load_integrations()

    def _load_integrations(self) -> None:
        """Load all known integrations."""
        # Add each integration - easy to extend!
        integrations: list[BaseIntegration] = [
            SlackIntegration(),
            GitHubIntegration(),
            NotionIntegration(),
        ]

        for integration in integrations:
            self._integrations[integration.provider_id] = integration
            logger.debug(
                "integration_registered",
                provider_id=integration.provider_id,
                configured=integration.is_configured(),
            )

    def get_integration(self, provider_id: str) -> BaseIntegration:
        """Get integration by provider ID.

        Args:
            provider_id: Provider identifier (e.g., 'slack', 'github', 'notion')

        Returns:
            Integration instance

        Raises:
            IntegrationNotFoundError: If provider not found
        """
        integration = self._integrations.get(provider_id.lower())
        if integration is None:
            raise IntegrationNotFoundError(
                f"Integration not found: {provider_id}. "
                f"Available: {list(self._integrations.keys())}"
            )
        return integration

    def get_oauth_config(self, provider_id: str) -> OAuthConfig:
        """Get OAuth configuration for a provider.

        Args:
            provider_id: Provider identifier

        Returns:
            OAuth configuration

        Raises:
            IntegrationNotFoundError: If provider not found
            IntegrationNotConfiguredError: If not configured
        """
        integration = self.get_integration(provider_id)
        config = integration.get_oauth_config()

        if not config.client_id or not config.client_secret:
            raise IntegrationNotConfiguredError(
                f"Integration {provider_id} is not configured. "
                f"Set {provider_id.upper()}_CLIENT_ID and {provider_id.upper()}_CLIENT_SECRET."
            )

        return config

    def get_authorization_url(
        self,
        provider_id: str,
        state: str,
        extra_scopes: list[str] | None = None,
    ) -> str:
        """Generate OAuth authorization URL.

        Args:
            provider_id: Provider identifier
            state: State parameter for CSRF protection
            extra_scopes: Additional scopes to request

        Returns:
            Authorization URL

        Raises:
            IntegrationNotFoundError: If provider not found
            IntegrationNotConfiguredError: If not configured
        """
        integration = self.get_integration(provider_id)
        config = self.get_oauth_config(provider_id)

        params = integration.build_authorization_params(config, state, extra_scopes)
        auth_url = f"{config.authorize_url}?{urlencode(params)}"

        logger.info(
            "oauth_authorization_url_generated",
            provider=provider_id,
            redirect_uri=config.redirect_uri,
        )

        return auth_url

    async def exchange_code(
        self,
        provider_id: str,
        code: str,
    ) -> OAuthTokens:
        """Exchange authorization code for tokens.

        Args:
            provider_id: Provider identifier
            code: Authorization code from callback

        Returns:
            OAuth tokens

        Raises:
            IntegrationNotFoundError: If provider not found
            IntegrationNotConfiguredError: If not configured
            IntegrationCodeExchangeError: If exchange fails
        """
        integration = self.get_integration(provider_id)
        config = self.get_oauth_config(provider_id)

        try:
            async with httpx.AsyncClient() as client:
                return await integration.exchange_code(client, config, code)
        except Exception as e:
            raise IntegrationCodeExchangeError(
                f"Token exchange failed for {provider_id}: {e}"
            ) from e

    def build_credential_data(
        self,
        provider_id: str,
        tokens: OAuthTokens,
    ) -> dict[str, Any]:
        """Build credential data from OAuth tokens.

        Args:
            provider_id: Provider identifier
            tokens: OAuth tokens

        Returns:
            Dict suitable for CredentialCreate.data
        """
        integration = self.get_integration(provider_id)
        return integration.build_credential_data(tokens)

    def list_integrations(self) -> list[dict[str, Any]]:
        """List all available integrations.

        Returns:
            List of integration info dicts
        """
        result = []
        for provider_id, integration in self._integrations.items():
            config = integration.get_oauth_config()
            result.append({
                "provider_id": provider_id,
                "display_name": integration.display_name,
                "configured": integration.is_configured(),
                "credential_type": config.credential_type,
                "mcp_server_id": config.mcp_server_id,
            })
        return result

    def list_configured_integrations(self) -> list[dict[str, Any]]:
        """List only configured integrations.

        Returns:
            List of configured integration info dicts
        """
        return [i for i in self.list_integrations() if i["configured"]]


@lru_cache
def get_integration_registry() -> IntegrationRegistry:
    """Get cached integration registry instance."""
    return IntegrationRegistry()
