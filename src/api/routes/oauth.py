"""OAuth routes.

Handles OAuth authorization flow for external integrations.
Provides endpoints for authorization URL generation and callback handling.
"""

import secrets
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from src.api.deps import CurrentUser, DBSession, get_credential_service
from src.config import settings
from src.integrations import IntegrationRegistry, get_integration_registry
from src.integrations.registry import (
    IntegrationCodeExchangeError,
    IntegrationNotConfiguredError,
    IntegrationNotFoundError,
)
from src.models.credential import CredentialCreate
from src.services.credential_service import CredentialService

logger = structlog.get_logger()

router = APIRouter(prefix="/oauth", tags=["oauth"])

# In-memory state storage (use Redis in production for distributed systems)
# Maps state -> {user_id, redirect_to}
_oauth_states: dict[str, dict[str, str]] = {}


def get_registry() -> IntegrationRegistry:
    """Get integration registry instance."""
    return get_integration_registry()


IntegrationRegistryDep = Annotated[IntegrationRegistry, Depends(get_registry)]


def generate_state() -> str:
    """Generate a secure random state parameter."""
    return secrets.token_urlsafe(32)


@router.get(
    "/providers",
    summary="List OAuth providers",
    description="Get list of available OAuth providers and their configuration status.",
)
async def list_providers(
    registry: IntegrationRegistryDep,
) -> list[dict[str, Any]]:
    """List available OAuth providers.

    Returns:
        List of provider info with configuration status
    """
    return registry.list_integrations()


@router.get(
    "/{provider}/authorize",
    summary="Get authorization URL",
    description="Generate OAuth authorization URL for the specified provider.",
)
async def get_authorization_url(
    provider: str,
    user: CurrentUser,
    registry: IntegrationRegistryDep,
    redirect_to: str | None = Query(
        default=None,
        description="URL to redirect to after OAuth completion (default: frontend_url)",
    ),
) -> dict[str, str]:
    """Generate OAuth authorization URL.

    The user must be authenticated to initiate OAuth flow.
    A state parameter is generated for CSRF protection.

    Args:
        provider: OAuth provider name (slack, github, notion)
        user: Current authenticated user
        registry: Integration registry
        redirect_to: Optional URL to redirect to after completion

    Returns:
        Dict with authorization URL

    Raises:
        HTTPException 404: If provider is unknown
        HTTPException 400: If provider is not configured
    """
    try:
        # Generate state for CSRF protection
        state = generate_state()

        # Store state with user_id and redirect URL
        _oauth_states[state] = {
            "user_id": user.id,
            "redirect_to": redirect_to or settings.frontend_url,
        }

        auth_url = registry.get_authorization_url(
            provider_id=provider,
            state=state,
        )

        logger.info(
            "oauth_authorization_initiated",
            provider=provider,
            user_id=user.id,
        )

        return {
            "authorization_url": auth_url,
            "state": state,
        }

    except IntegrationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except IntegrationNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/{provider}/callback",
    summary="OAuth callback",
    description="Handle OAuth callback from provider. Exchanges code for tokens and stores credential.",
)
async def oauth_callback(
    provider: str,
    session: DBSession,
    registry: IntegrationRegistryDep,
    credential_service: Annotated[CredentialService, Depends(get_credential_service)],
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="State parameter for CSRF validation"),
    error: str | None = Query(default=None, description="Error from provider"),
    error_description: str | None = Query(default=None, description="Error description"),
) -> RedirectResponse:
    """Handle OAuth callback.

    This endpoint is called by the OAuth provider after user authorization.
    It exchanges the authorization code for tokens and stores them as a credential.

    Args:
        provider: OAuth provider name
        session: Database session
        registry: Integration registry
        credential_service: Credential service
        code: Authorization code from provider
        state: State parameter for CSRF validation
        error: Error from provider (if authorization failed)
        error_description: Error description from provider

    Returns:
        Redirect to frontend with success/error status
    """
    # Check for error from provider
    if error:
        logger.warning(
            "oauth_callback_error_from_provider",
            provider=provider,
            error=error,
            error_description=error_description,
        )
        redirect_url = f"{settings.frontend_url}/integrations?error={error}"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    # Validate state
    state_data = _oauth_states.pop(state, None)
    if state_data is None:
        logger.warning(
            "oauth_callback_invalid_state",
            provider=provider,
        )
        redirect_url = f"{settings.frontend_url}/integrations?error=invalid_state"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    user_id = state_data["user_id"]
    redirect_to = state_data["redirect_to"]

    try:
        # Get integration config
        config = registry.get_oauth_config(provider)

        # Exchange code for tokens
        tokens = await registry.exchange_code(
            provider_id=provider,
            code=code,
        )

        # Build credential data
        credential_data = registry.build_credential_data(provider, tokens)

        # Create credential
        credential = await credential_service.create(
            user_id=user_id,
            data=CredentialCreate(
                name=f"{config.display_name} Connection",
                credential_type=config.credential_type,
                data=credential_data,
                mcp_server_id=config.mcp_server_id,
            ),
        )

        logger.info(
            "oauth_credential_created",
            provider=provider,
            user_id=user_id,
            credential_id=credential.id,
        )

        # Redirect to frontend with success
        redirect_url = f"{redirect_to}/integrations?success=true&provider={provider}"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    except IntegrationNotFoundError as e:
        logger.error(
            "oauth_callback_provider_not_found",
            provider=provider,
            error=str(e),
        )
        redirect_url = f"{redirect_to}/integrations?error=provider_not_found"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    except IntegrationNotConfiguredError as e:
        logger.error(
            "oauth_callback_provider_not_configured",
            provider=provider,
            error=str(e),
        )
        redirect_url = f"{redirect_to}/integrations?error=provider_not_configured"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    except IntegrationCodeExchangeError as e:
        logger.error(
            "oauth_callback_code_exchange_failed",
            provider=provider,
            error=str(e),
        )
        redirect_url = f"{redirect_to}/integrations?error=token_exchange_failed"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        logger.exception(
            "oauth_callback_unexpected_error",
            provider=provider,
            error=str(e),
        )
        redirect_url = f"{redirect_to}/integrations?error=unexpected_error"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.delete(
    "/{provider}/disconnect",
    summary="Disconnect OAuth integration",
    description="Remove OAuth credential for the specified provider.",
)
async def disconnect_provider(
    provider: str,
    user: CurrentUser,
    session: DBSession,
    registry: IntegrationRegistryDep,
    credential_service: Annotated[CredentialService, Depends(get_credential_service)],
) -> dict[str, str]:
    """Disconnect OAuth integration.

    Removes the stored credential for the specified provider.

    Args:
        provider: OAuth provider name
        user: Current authenticated user
        session: Database session
        registry: Integration registry
        credential_service: Credential service

    Returns:
        Success message

    Raises:
        HTTPException 404: If no credential found for provider
    """
    try:
        config = registry.get_oauth_config(provider)
        credential_type = config.credential_type
    except IntegrationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except IntegrationNotConfiguredError:
        # Provider not configured, but we can still try to delete credentials
        # Use the provider name as credential type fallback
        integration = registry.get_integration(provider)
        credential_type = integration.get_oauth_config().credential_type

    # Find and delete credential
    credentials = await credential_service.list_all(
        user_id=user.id,
        credential_type=credential_type,
    )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider} connection found",
        )

    # Delete all matching credentials
    for cred in credentials:
        await credential_service.delete(
            credential_id=cred.id,
            user_id=user.id,
        )

    logger.info(
        "oauth_disconnected",
        provider=provider,
        user_id=user.id,
        credentials_removed=len(credentials),
    )

    return {"message": f"{provider.title()} disconnected successfully"}


@router.get(
    "/{provider}/status",
    summary="Get connection status",
    description="Check if user has connected the specified OAuth provider.",
)
async def get_connection_status(
    provider: str,
    user: CurrentUser,
    registry: IntegrationRegistryDep,
    credential_service: Annotated[CredentialService, Depends(get_credential_service)],
) -> dict[str, Any]:
    """Get OAuth connection status.

    Check if the user has an active credential for the specified provider.

    Args:
        provider: OAuth provider name
        user: Current authenticated user
        registry: Integration registry
        credential_service: Credential service

    Returns:
        Connection status with credential info
    """
    try:
        integration = registry.get_integration(provider)
        config = integration.get_oauth_config()
        is_configured = integration.is_configured()
    except IntegrationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

    # Check for existing credential
    credentials = await credential_service.list_all(
        user_id=user.id,
        credential_type=config.credential_type,
    )

    connected = len(credentials) > 0
    credential_info = None
    if connected and credentials:
        cred = credentials[0]
        credential_info = {
            "id": cred.id,
            "name": cred.name,
            "created_at": cred.created_at.isoformat(),
        }

    return {
        "provider": provider,
        "display_name": integration.display_name,
        "configured": is_configured,
        "connected": connected,
        "credential": credential_info,
    }
