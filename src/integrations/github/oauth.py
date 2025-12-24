"""GitHub OAuth integration.

Implements OAuth 2.0 flow for GitHub.
Docs: https://docs.github.com/en/developers/apps/building-oauth-apps/authorizing-oauth-apps
"""

from typing import Any

import httpx
import structlog

from src.config import settings
from src.integrations.base import BaseIntegration, OAuthConfig, OAuthTokens

logger = structlog.get_logger()


class GitHubOAuthError(Exception):
    """GitHub OAuth error."""

    pass


class GitHubIntegration(BaseIntegration):
    """GitHub integration implementation."""

    @property
    def provider_id(self) -> str:
        return "github"

    @property
    def display_name(self) -> str:
        return "GitHub"

    def get_oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            provider_id=self.provider_id,
            display_name=self.display_name,
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

    def build_authorization_params(
        self,
        config: OAuthConfig,
        state: str,
        extra_scopes: list[str] | None = None,
    ) -> dict[str, str]:
        scopes = config.scopes.copy()
        if extra_scopes:
            scopes.extend(extra_scopes)

        return {
            "client_id": config.client_id or "",
            "redirect_uri": config.redirect_uri,
            "state": state,
            "scope": " ".join(scopes),  # GitHub uses space-separated scopes
        }

    async def exchange_code(
        self,
        client: httpx.AsyncClient,
        config: OAuthConfig,
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
                raise GitHubOAuthError(f"GitHub OAuth exchange failed: {error}")

            access_token = data.get("access_token")
            if not access_token:
                raise GitHubOAuthError("No access token in GitHub response")

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
            raise GitHubOAuthError(f"HTTP error during GitHub OAuth exchange: {e}") from e

    def build_credential_data(self, tokens: OAuthTokens) -> dict[str, Any]:
        data: dict[str, Any] = {
            "token": tokens.access_token,
        }
        if tokens.scope:
            data["scope"] = tokens.scope
        return data
