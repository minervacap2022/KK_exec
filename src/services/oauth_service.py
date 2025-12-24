"""OAuth service.

Handles OAuth flows for external integrations (Slack, GitHub, Notion, etc.).
Provides authorization URL generation and token exchange.
"""

import base64
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger()


class OAuthProvider(str, Enum):
    """Supported OAuth providers."""

    SLACK = "slack"
    GITHUB = "github"
    NOTION = "notion"


class OAuthError(Exception):
    """Base OAuth error."""

    pass


class OAuthProviderNotConfiguredError(OAuthError):
    """OAuth provider is not configured (missing client_id/secret)."""

    pass


class OAuthCodeExchangeError(OAuthError):
    """Failed to exchange authorization code for tokens."""

    pass


class OAuthProviderNotFoundError(OAuthError):
    """Unknown OAuth provider."""

    pass


@dataclass
class OAuthTokens:
    """OAuth tokens returned from token exchange."""

    access_token: str
    token_type: str = "Bearer"
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scope: str | None = None
    raw_response: dict[str, Any] | None = None


@dataclass
class OAuthProviderConfig:
    """Configuration for an OAuth provider."""

    provider: OAuthProvider
    client_id: str | None
    client_secret: str | None
    redirect_uri: str
    authorize_url: str
    token_url: str
    scopes: list[str]
    credential_type: str
    mcp_server_id: str | None


# OAuth provider configurations
OAUTH_PROVIDERS: dict[OAuthProvider, OAuthProviderConfig] = {
    OAuthProvider.SLACK: OAuthProviderConfig(
        provider=OAuthProvider.SLACK,
        client_id=None,  # Set from settings at runtime
        client_secret=None,  # Set from settings at runtime
        redirect_uri="",  # Set from settings at runtime
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=[
            "channels:read",
            "chat:write",
            "users:read",
            "files:read",
        ],
        credential_type="slack_oauth",
        mcp_server_id="slack",
    ),
    OAuthProvider.GITHUB: OAuthProviderConfig(
        provider=OAuthProvider.GITHUB,
        client_id=None,  # Set from settings at runtime
        client_secret=None,  # Set from settings at runtime
        redirect_uri="",  # Set from settings at runtime
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes=[
            "repo",
            "read:user",
        ],
        credential_type="github_token",
        mcp_server_id="github",
    ),
}


class OAuthService:
    """Service for handling OAuth flows.

    Provides:
    - Authorization URL generation with state parameter
    - Token exchange (authorization code → access token)
    - Provider configuration management

    Example usage:
        service = OAuthService()

        # Generate authorization URL
        auth_url = service.get_authorization_url(
            provider="slack",
            state="random-state-value"
        )

        # After user authorizes, exchange code for tokens
        tokens = await service.exchange_code(
            provider="slack",
            code="authorization-code-from-callback"
        )
    """

    def __init__(self) -> None:
        """Initialize OAuth service with provider configurations."""
        self._providers = self._load_provider_configs()

    def _load_provider_configs(self) -> dict[OAuthProvider, OAuthProviderConfig]:
        """Load provider configurations from settings."""
        configs = {}

        # Slack
        slack_config = OAuthProviderConfig(
            provider=OAuthProvider.SLACK,
            client_id=settings.slack_client_id,
            client_secret=(
                settings.slack_client_secret.get_secret_value()
                if settings.slack_client_secret
                else None
            ),
            redirect_uri=settings.slack_redirect_uri,
            authorize_url="https://slack.com/oauth/v2/authorize",
            token_url="https://slack.com/api/oauth.v2.access",
            scopes=[
                "channels:read",
                "chat:write",
                "users:read",
                "files:read",
            ],
            credential_type="slack_oauth",
            mcp_server_id="slack",
        )
        configs[OAuthProvider.SLACK] = slack_config

        # GitHub
        github_config = OAuthProviderConfig(
            provider=OAuthProvider.GITHUB,
            client_id=settings.github_client_id,
            client_secret=(
                settings.github_client_secret.get_secret_value()
                if settings.github_client_secret
                else None
            ),
            redirect_uri=settings.github_redirect_uri,
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            scopes=[
                "repo",
                "read:user",
            ],
            credential_type="github_token",
            mcp_server_id="github",
        )
        configs[OAuthProvider.GITHUB] = github_config

        # Notion
        notion_config = OAuthProviderConfig(
            provider=OAuthProvider.NOTION,
            client_id=settings.notion_client_id,
            client_secret=(
                settings.notion_client_secret.get_secret_value()
                if settings.notion_client_secret
                else None
            ),
            redirect_uri=settings.notion_redirect_uri,
            authorize_url="https://api.notion.com/v1/oauth/authorize",
            token_url="https://api.notion.com/v1/oauth/token",
            scopes=[],  # Notion doesn't use scopes in authorization URL
            credential_type="notion_oauth",
            mcp_server_id="notion",
        )
        configs[OAuthProvider.NOTION] = notion_config

        return configs

    def get_provider_config(self, provider: str) -> OAuthProviderConfig:
        """Get configuration for a provider.

        Args:
            provider: Provider name (slack, github)

        Returns:
            Provider configuration

        Raises:
            OAuthProviderNotFoundError: If provider is unknown
            OAuthProviderNotConfiguredError: If provider is not configured
        """
        try:
            oauth_provider = OAuthProvider(provider.lower())
        except ValueError as e:
            raise OAuthProviderNotFoundError(
                f"Unknown OAuth provider: {provider}"
            ) from e

        config = self._providers.get(oauth_provider)
        if config is None:
            raise OAuthProviderNotFoundError(
                f"OAuth provider not found: {provider}"
            )

        if not config.client_id or not config.client_secret:
            raise OAuthProviderNotConfiguredError(
                f"OAuth provider {provider} is not configured. "
                f"Set {provider.upper()}_CLIENT_ID and {provider.upper()}_CLIENT_SECRET environment variables."
            )

        return config

    def generate_state(self) -> str:
        """Generate a secure random state parameter.

        Returns:
            URL-safe random string for CSRF protection
        """
        return secrets.token_urlsafe(32)

    def get_authorization_url(
        self,
        provider: str,
        state: str,
        extra_scopes: list[str] | None = None,
    ) -> str:
        """Generate OAuth authorization URL.

        Args:
            provider: OAuth provider name
            state: State parameter for CSRF protection
            extra_scopes: Additional scopes to request

        Returns:
            Authorization URL to redirect user to

        Raises:
            OAuthProviderNotFoundError: If provider is unknown
            OAuthProviderNotConfiguredError: If provider is not configured
        """
        config = self.get_provider_config(provider)

        scopes = config.scopes.copy()
        if extra_scopes:
            scopes.extend(extra_scopes)

        params: dict[str, str] = {
            "client_id": config.client_id,  # type: ignore
            "redirect_uri": config.redirect_uri,
            "state": state,
        }

        # Provider-specific parameters
        if config.provider == OAuthProvider.SLACK:
            params["scope"] = ",".join(scopes)
        elif config.provider == OAuthProvider.GITHUB:
            params["scope"] = " ".join(scopes)
        elif config.provider == OAuthProvider.NOTION:
            # Notion requires owner=user and response_type=code
            params["owner"] = "user"
            params["response_type"] = "code"
            # Notion doesn't use scopes in authorization URL
        else:
            params["scope"] = " ".join(scopes)

        auth_url = f"{config.authorize_url}?{urlencode(params)}"

        logger.info(
            "oauth_authorization_url_generated",
            provider=provider,
            redirect_uri=config.redirect_uri,
        )

        return auth_url

    async def exchange_code(
        self,
        provider: str,
        code: str,
    ) -> OAuthTokens:
        """Exchange authorization code for access tokens.

        Args:
            provider: OAuth provider name
            code: Authorization code from callback

        Returns:
            OAuth tokens

        Raises:
            OAuthProviderNotFoundError: If provider is unknown
            OAuthProviderNotConfiguredError: If provider is not configured
            OAuthCodeExchangeError: If token exchange fails
        """
        config = self.get_provider_config(provider)

        async with httpx.AsyncClient() as client:
            if config.provider == OAuthProvider.SLACK:
                return await self._exchange_slack_code(client, config, code)
            elif config.provider == OAuthProvider.GITHUB:
                return await self._exchange_github_code(client, config, code)
            elif config.provider == OAuthProvider.NOTION:
                return await self._exchange_notion_code(client, config, code)
            else:
                raise OAuthProviderNotFoundError(
                    f"Token exchange not implemented for: {provider}"
                )

    async def _exchange_slack_code(
        self,
        client: httpx.AsyncClient,
        config: OAuthProviderConfig,
        code: str,
    ) -> OAuthTokens:
        """Exchange Slack authorization code for tokens."""
        try:
            response = await client.post(
                config.token_url,
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                error = data.get("error", "unknown_error")
                logger.error(
                    "slack_oauth_exchange_failed",
                    error=error,
                )
                raise OAuthCodeExchangeError(
                    f"Slack OAuth exchange failed: {error}"
                )

            # Slack returns tokens in authed_user for user tokens
            authed_user = data.get("authed_user", {})
            access_token = authed_user.get("access_token") or data.get("access_token")

            if not access_token:
                raise OAuthCodeExchangeError(
                    "No access token in Slack response"
                )

            logger.info(
                "slack_oauth_exchange_success",
                team_id=data.get("team", {}).get("id"),
            )

            return OAuthTokens(
                access_token=access_token,
                token_type="Bearer",
                refresh_token=authed_user.get("refresh_token"),
                scope=authed_user.get("scope") or data.get("scope"),
                raw_response=data,
            )

        except httpx.HTTPError as e:
            logger.error(
                "slack_oauth_exchange_http_error",
                error=str(e),
            )
            raise OAuthCodeExchangeError(
                f"HTTP error during Slack OAuth exchange: {e}"
            ) from e

    async def _exchange_github_code(
        self,
        client: httpx.AsyncClient,
        config: OAuthProviderConfig,
        code: str,
    ) -> OAuthTokens:
        """Exchange GitHub authorization code for tokens."""
        try:
            response = await client.post(
                config.token_url,
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                },
                headers={
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                error = data.get("error_description", data.get("error"))
                logger.error(
                    "github_oauth_exchange_failed",
                    error=error,
                )
                raise OAuthCodeExchangeError(
                    f"GitHub OAuth exchange failed: {error}"
                )

            access_token = data.get("access_token")
            if not access_token:
                raise OAuthCodeExchangeError(
                    "No access token in GitHub response"
                )

            logger.info("github_oauth_exchange_success")

            return OAuthTokens(
                access_token=access_token,
                token_type=data.get("token_type", "Bearer"),
                refresh_token=data.get("refresh_token"),
                scope=data.get("scope"),
                raw_response=data,
            )

        except httpx.HTTPError as e:
            logger.error(
                "github_oauth_exchange_http_error",
                error=str(e),
            )
            raise OAuthCodeExchangeError(
                f"HTTP error during GitHub OAuth exchange: {e}"
            ) from e

    async def _exchange_notion_code(
        self,
        client: httpx.AsyncClient,
        config: OAuthProviderConfig,
        code: str,
    ) -> OAuthTokens:
        """Exchange Notion authorization code for tokens.

        Notion uses HTTP Basic Auth for token exchange.
        """
        try:
            # Build Basic Auth header (base64 encoded client_id:client_secret)
            credentials = f"{config.client_id}:{config.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            response = await client.post(
                config.token_url,
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                },
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28",
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                error = data.get("error_description", data.get("error"))
                logger.error(
                    "notion_oauth_exchange_failed",
                    error=error,
                )
                raise OAuthCodeExchangeError(
                    f"Notion OAuth exchange failed: {error}"
                )

            access_token = data.get("access_token")
            if not access_token:
                raise OAuthCodeExchangeError(
                    "No access token in Notion response"
                )

            logger.info(
                "notion_oauth_exchange_success",
                workspace_id=data.get("workspace_id"),
                bot_id=data.get("bot_id"),
            )

            return OAuthTokens(
                access_token=access_token,
                token_type=data.get("token_type", "Bearer"),
                refresh_token=data.get("refresh_token"),
                raw_response=data,
            )

        except httpx.HTTPError as e:
            logger.error(
                "notion_oauth_exchange_http_error",
                error=str(e),
            )
            raise OAuthCodeExchangeError(
                f"HTTP error during Notion OAuth exchange: {e}"
            ) from e

    def get_available_providers(self) -> list[dict[str, Any]]:
        """Get list of available OAuth providers.

        Returns:
            List of provider info with configuration status
        """
        providers = []
        for provider, config in self._providers.items():
            is_configured = bool(config.client_id and config.client_secret)
            providers.append({
                "provider": provider.value,
                "display_name": provider.value.title(),
                "configured": is_configured,
                "credential_type": config.credential_type,
                "mcp_server_id": config.mcp_server_id,
            })
        return providers

    def build_credential_data(
        self,
        provider: str,
        tokens: OAuthTokens,
    ) -> dict[str, Any]:
        """Build credential data from OAuth tokens.

        Args:
            provider: OAuth provider name
            tokens: Tokens from exchange

        Returns:
            Dict suitable for CredentialCreate.data
        """
        config = self.get_provider_config(provider)

        if config.provider == OAuthProvider.SLACK:
            data = {
                "access_token": tokens.access_token,
            }
            if tokens.refresh_token:
                data["refresh_token"] = tokens.refresh_token
            if tokens.expires_at:
                data["expires_at"] = tokens.expires_at.isoformat()
            if tokens.scope:
                data["scope"] = tokens.scope
            return data

        elif config.provider == OAuthProvider.GITHUB:
            data = {
                "token": tokens.access_token,
            }
            if tokens.scope:
                data["scope"] = tokens.scope
            return data

        elif config.provider == OAuthProvider.NOTION:
            data = {
                "access_token": tokens.access_token,
            }
            if tokens.refresh_token:
                data["refresh_token"] = tokens.refresh_token
            # Store Notion-specific metadata from raw_response
            if tokens.raw_response:
                if tokens.raw_response.get("workspace_id"):
                    data["workspace_id"] = tokens.raw_response["workspace_id"]
                if tokens.raw_response.get("workspace_name"):
                    data["workspace_name"] = tokens.raw_response["workspace_name"]
                if tokens.raw_response.get("bot_id"):
                    data["bot_id"] = tokens.raw_response["bot_id"]
            return data

        else:
            return {
                "access_token": tokens.access_token,
            }
