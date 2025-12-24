"""Notion OAuth integration.

Implements OAuth 2.0 flow for Notion.
Docs: https://developers.notion.com/docs/authorization
"""

from typing import Any

import httpx
import structlog

from src.config import settings
from src.integrations.base import BaseIntegration, OAuthConfig, OAuthTokens

logger = structlog.get_logger()


class NotionOAuthError(Exception):
    """Notion OAuth error."""

    pass


class NotionIntegration(BaseIntegration):
    """Notion integration implementation."""

    @property
    def provider_id(self) -> str:
        return "notion"

    @property
    def display_name(self) -> str:
        return "Notion"

    def get_oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            provider_id=self.provider_id,
            display_name=self.display_name,
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

    def build_authorization_params(
        self,
        config: OAuthConfig,
        state: str,
        extra_scopes: list[str] | None = None,
    ) -> dict[str, str]:
        # Notion requires owner=user and response_type=code
        return {
            "client_id": config.client_id or "",
            "redirect_uri": config.redirect_uri,
            "state": state,
            "owner": "user",
            "response_type": "code",
        }

    async def exchange_code(
        self,
        client: httpx.AsyncClient,
        config: OAuthConfig,
        code: str,
    ) -> OAuthTokens:
        """Exchange Notion authorization code for tokens.

        Notion uses HTTP Basic Auth for token exchange.
        """
        try:
            # Build Basic Auth header
            auth_header = self.build_basic_auth_header(
                config.client_id or "",
                config.client_secret or "",
            )

            response = await client.post(
                config.token_url,
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                },
                headers={
                    "Authorization": auth_header,
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
                raise NotionOAuthError(f"Notion OAuth exchange failed: {error}")

            access_token = data.get("access_token")
            if not access_token:
                raise NotionOAuthError("No access token in Notion response")

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
            raise NotionOAuthError(f"HTTP error during Notion OAuth exchange: {e}") from e

    def build_credential_data(self, tokens: OAuthTokens) -> dict[str, Any]:
        data: dict[str, Any] = {
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
            # Store owner info
            owner = tokens.raw_response.get("owner", {})
            if owner.get("user"):
                user = owner["user"]
                if user.get("id"):
                    data["user_id"] = user["id"]
                if user.get("name"):
                    data["user_name"] = user["name"]
        return data
