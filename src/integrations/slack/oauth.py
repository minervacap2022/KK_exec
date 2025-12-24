"""Slack OAuth integration.

Implements OAuth 2.0 flow for Slack.
Docs: https://api.slack.com/authentication/oauth-v2
"""

from typing import Any

import httpx
import structlog

from src.config import settings
from src.integrations.base import BaseIntegration, OAuthConfig, OAuthTokens

logger = structlog.get_logger()


class SlackOAuthError(Exception):
    """Slack OAuth error."""

    pass


class SlackIntegration(BaseIntegration):
    """Slack integration implementation."""

    @property
    def provider_id(self) -> str:
        return "slack"

    @property
    def display_name(self) -> str:
        return "Slack"

    def get_oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            provider_id=self.provider_id,
            display_name=self.display_name,
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
            "scope": ",".join(scopes),  # Slack uses comma-separated scopes
        }

    async def exchange_code(
        self,
        client: httpx.AsyncClient,
        config: OAuthConfig,
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
                raise SlackOAuthError(f"Slack OAuth exchange failed: {error}")

            # Slack returns tokens in authed_user for user tokens
            authed_user = data.get("authed_user", {})
            access_token = authed_user.get("access_token") or data.get("access_token")

            if not access_token:
                raise SlackOAuthError("No access token in Slack response")

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
            raise SlackOAuthError(f"HTTP error during Slack OAuth exchange: {e}") from e

    def build_credential_data(self, tokens: OAuthTokens) -> dict[str, Any]:
        data: dict[str, Any] = {
            "access_token": tokens.access_token,
        }
        if tokens.refresh_token:
            data["refresh_token"] = tokens.refresh_token
        if tokens.expires_at:
            data["expires_at"] = tokens.expires_at.isoformat()
        if tokens.scope:
            data["scope"] = tokens.scope
        # Store team info from raw response
        if tokens.raw_response:
            team = tokens.raw_response.get("team", {})
            if team.get("id"):
                data["team_id"] = team["id"]
            if team.get("name"):
                data["team_name"] = team["name"]
        return data
