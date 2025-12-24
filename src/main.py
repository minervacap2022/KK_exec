"""FastAPI application entry point.

This module initializes the FastAPI application with all routes,
middleware, and lifecycle handlers.
"""

import logging
import structlog
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from src.api.deps import _async_session_maker, get_db_session
from src.api.routes import (
    auth_router,
    credentials_router,
    executions_router,
    mcp_router,
    nodes_router,
    oauth_router,
    workflows_router,
)
from src.config import settings
from src.services.execution_service import init_execution_service

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer() if not settings.debug else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info(
        "application_starting",
        host=settings.host,
        port=settings.port,
        debug=settings.debug,
        log_level=settings.log_level,
    )

    # Validate critical configuration
    try:
        # Test encryption key format
        from cryptography.fernet import Fernet
        Fernet(settings.encryption_key.get_secret_value().encode())
        logger.info("encryption_key_validated")
    except Exception as e:
        logger.error("encryption_key_invalid", error=str(e))
        raise ValueError("Invalid ENCRYPTION_KEY format") from e

    logger.info(
        "configuration_loaded",
        openai_key=settings.get_masked_key("openai_api_key"),
        default_model=settings.default_model,
        mcp_timeout=settings.mcp_timeout,
    )

    # Initialize execution service with session maker for background tasks
    init_execution_service(_async_session_maker)

    yield

    # Shutdown
    logger.info("application_shutting_down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="KK Workflow Automation",
        description="MCP-based workflow automation system with NLP-driven workflow creation",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    app.include_router(
        workflows_router,
        prefix="/api/v1/workflows",
        tags=["workflows"],
    )
    app.include_router(
        nodes_router,
        prefix="/api/v1/nodes",
        tags=["nodes"],
    )
    app.include_router(
        credentials_router,
        prefix="/api/v1/credentials",
        tags=["credentials"],
    )
    app.include_router(
        executions_router,
        prefix="/api/v1/executions",
        tags=["executions"],
    )
    app.include_router(
        mcp_router,
        prefix="/api/v1/mcp",
        tags=["mcp"],
    )
    app.include_router(
        auth_router,
        prefix="/api/v1",
    )
    app.include_router(
        oauth_router,
        prefix="/api/v1",
    )

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle uncaught exceptions.

        Never expose internal error details in production.
        """
        logger.exception(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error_type=type(exc).__name__,
        )

        if settings.debug:
            detail = str(exc)
        else:
            detail = "An internal error occurred"

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": detail, "error_type": "internal_error"},
        )

    # Health check endpoint
    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Health check endpoint for load balancers and monitoring."""
        return {"status": "healthy", "version": "0.1.0"}

    # Ready check endpoint (includes dependency checks)
    @app.get("/ready", tags=["health"])
    async def ready_check() -> dict[str, str]:
        """Readiness check including database connectivity."""
        try:
            async for session in get_db_session():
                await session.execute("SELECT 1")
            return {"status": "ready"}
        except Exception as e:
            logger.error("readiness_check_failed", error=str(e))
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "error": "database_unavailable"},
            )

    # Instrument with OpenTelemetry
    FastAPIInstrumentor.instrument_app(app)

    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
