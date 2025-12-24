"""MCP Credential Injector.

Handles injection of user-specific credentials into MCP connections.
"""

from dataclasses import dataclass
from typing import Any

import structlog

from src.models.credential import CredentialDecrypted
from src.mcp.server_registry import MCPServerConfig

logger = structlog.get_logger()


class CredentialInjectionError(Exception):
    """Error during credential injection."""

    pass


@dataclass
class InjectedCredentials:
    """Credentials prepared for injection into MCP connection."""

    headers: dict[str, str]
    params: dict[str, Any]
    env: dict[str, str]


class CredentialInjector:
    """Injects user credentials into MCP server connections.

    Handles different authentication methods:
    - Bearer tokens (OAuth)
    - API keys (header or query param)
    - Environment variables (for stdio)

    Example usage:
        injector = CredentialInjector()
        creds = injector.prepare(server_config, user_credential)
        transport = create_transport(
            server_config.transport,
            headers=creds.headers,
            ...
        )
    """

    # Mapping of credential types to injection strategies
    CREDENTIAL_STRATEGIES = {
        "slack_oauth": {
            "method": "bearer",
            "token_field": "access_token",
        },
        "github_token": {
            "method": "bearer",
            "token_field": "token",
        },
        "openai_api_key": {
            "method": "bearer",
            "token_field": "api_key",
        },
        "anthropic_api_key": {
            "method": "header",
            "header_name": "x-api-key",
            "token_field": "api_key",
        },
        "google_oauth": {
            "method": "bearer",
            "token_field": "access_token",
        },
        "notion_token": {
            "method": "bearer",
            "token_field": "token",
        },
        "weather_api_key": {
            "method": "query",
            "param_name": "appid",
            "token_field": "api_key",
        },
        "generic_api_key": {
            "method": "header",
            "header_name": "X-API-Key",
            "token_field": "api_key",
        },
    }

    def prepare(
        self,
        server_config: MCPServerConfig,
        credential: CredentialDecrypted | None,
    ) -> InjectedCredentials:
        """Prepare credentials for injection.

        Args:
            server_config: MCP server configuration
            credential: User's decrypted credential (None if no auth needed)

        Returns:
            Prepared credentials for transport

        Raises:
            CredentialInjectionError: If injection fails
        """
        headers: dict[str, str] = {}
        params: dict[str, Any] = {}
        env: dict[str, str] = {}

        # No auth required
        if server_config.credential_type is None:
            logger.debug(
                "no_credential_required",
                server_id=server_config.id,
            )
            return InjectedCredentials(headers=headers, params=params, env=env)

        # Auth required but no credential provided
        if credential is None:
            raise CredentialInjectionError(
                f"Credential required for server '{server_config.id}' "
                f"(type: {server_config.credential_type})"
            )

        # Get injection strategy
        strategy = self.CREDENTIAL_STRATEGIES.get(credential.credential_type)
        if strategy is None:
            # Default to bearer token
            strategy = {
                "method": "bearer",
                "token_field": "token",
            }
            logger.warning(
                "unknown_credential_strategy",
                credential_type=credential.credential_type,
                using_default="bearer",
            )

        # Apply strategy
        method = strategy["method"]
        token_field = strategy["token_field"]
        token = credential.data.get(token_field)

        if not token:
            raise CredentialInjectionError(
                f"Missing required field '{token_field}' in credential"
            )

        if method == "bearer":
            headers["Authorization"] = f"Bearer {token}"

        elif method == "header":
            header_name = strategy.get("header_name", "X-API-Key")
            headers[header_name] = token

        elif method == "query":
            param_name = strategy.get("param_name", "api_key")
            params[param_name] = token

        elif method == "env":
            env_name = strategy.get("env_name", "API_KEY")
            env[env_name] = token

        logger.debug(
            "credentials_prepared",
            server_id=server_config.id,
            credential_type=credential.credential_type,
            method=method,
        )

        return InjectedCredentials(headers=headers, params=params, env=env)

    def prepare_for_transport(
        self,
        server_config: MCPServerConfig,
        credential: CredentialDecrypted | None,
    ) -> dict[str, Any]:
        """Prepare kwargs for transport creation.

        Args:
            server_config: MCP server configuration
            credential: User's decrypted credential

        Returns:
            Kwargs for create_transport()
        """
        injected = self.prepare(server_config, credential)

        if server_config.transport == "stdio":
            return {
                "command": server_config.command,
                "args": server_config.args,
                "env": {**(server_config.env or {}), **injected.env},
            }
        elif server_config.transport in ("streamable_http", "sse"):
            return {
                "url": server_config.url,
                "headers": injected.headers,
            }
        else:
            raise CredentialInjectionError(
                f"Unknown transport type: {server_config.transport}"
            )

    def validate_credential(
        self,
        credential_type: str,
        credential_data: dict[str, Any],
    ) -> list[str]:
        """Validate credential data has required fields.

        Args:
            credential_type: Type of credential
            credential_data: Raw credential data

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        strategy = self.CREDENTIAL_STRATEGIES.get(credential_type)
        if strategy is None:
            # Unknown type, accept any data
            return errors

        token_field = strategy.get("token_field")
        if token_field and token_field not in credential_data:
            errors.append(f"Missing required field: {token_field}")

        # Additional validation for OAuth tokens
        if credential_type.endswith("_oauth"):
            if "refresh_token" not in credential_data:
                errors.append("Missing refresh_token for OAuth credential")

        return errors
