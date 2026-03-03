# app.py
import logging
import os
import time

from contextlib import asynccontextmanager
from common.config.app_config import config
from common.database.database_factory import DatabaseFactory
from common.http_clients import close_shared_aiohttp_session
from common.models.messages_af import UserLanguage
from common.telemetry import current_trace_id
from opentelemetry import trace as otel_trace

# FastAPI imports
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Local imports
from middleware.health_check import HealthCheckMiddleware
from api.qbo import api_router as qbo_api_router
from api.qbo import router as qbo_router
from api.qbo_data import router as qbo_data_router
from api.reviews import router as reviews_router
from api.drive import router as drive_router
from v4.api.router import app_v4
from v4.config.settings import orchestration_config

# Azure monitoring


from v4.config.agent_registry import agent_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage FastAPI application lifecycle - startup and shutdown."""
    logger = logging.getLogger(__name__)

    # Startup
    logger.info("Starting MACAE application")
    yield

    # Shutdown
    logger.info("Shutting down MACAE application")
    try:
        # Clean up all agents from Azure AI Foundry when container stops
        await agent_registry.cleanup_all_agents()
        logger.info("Agent cleanup completed")

    except ImportError as ie:
        logger.error("Could not import agent_registry: %s", ie)
    except Exception as e:
        logger.error("Error during agent shutdown cleanup: %s", e)

    try:
        for user_id, wrappers in list(orchestration_config.agent_wrappers.items()):
            for wrapper in wrappers:
                close_coro = getattr(wrapper, "close", None)
                if callable(close_coro):
                    await close_coro()
            orchestration_config.agent_wrappers.pop(user_id, None)
    except Exception as e:
        logger.error("Error during wrapper cleanup: %s", e)

    try:
        await DatabaseFactory.close_all()
    except Exception as e:
        logger.error("Error closing database clients: %s", e)

    try:
        await close_shared_aiohttp_session()
    except Exception as e:
        logger.error("Error closing shared aiohttp session: %s", e)

    try:
        tracer_provider = otel_trace.get_tracer_provider()
        shutdown = getattr(tracer_provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception as e:
        logger.error("Error shutting down telemetry exporter: %s", e)

    logger.info("MACAE application shutdown complete")


_ENABLE_OTEL = False
connection_string = config.APPLICATIONINSIGHTS_CONNECTION_STRING
if connection_string:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create(
            {
                "service.name": "macae-backend",
                "service.namespace": "macae",
                "deployment.environment": str(config.APP_ENV).lower(),
            }
        )
        configure_azure_monitor(
            connection_string=connection_string,
            resource=resource,
            enable_live_metrics=True,
            instrumentation_options={
                # We instrument these manually below to keep behavior explicit.
                "fastapi": {"enabled": False},
                "requests": {"enabled": False},
                "urllib": {"enabled": False},
            },
        )
        _ENABLE_OTEL = True
        logging.info("Azure Monitor OpenTelemetry configured")
    except ImportError as exc:
        logging.warning(
            "Azure Monitor exporter unavailable; skipping Application Insights: %s",
            exc,
        )
    except Exception as exc:
        logging.warning(
            "Failed to configure Azure Monitor; continuing without telemetry: %s",
            exc,
        )
else:
    logging.warning(
        "No Application Insights Instrumentation Key found. Skipping configuration"
    )

# Configure logging levels from environment variables
logging.basicConfig(level=getattr(logging, config.AZURE_BASIC_LOGGING_LEVEL.upper(), logging.INFO))

# Configure Azure package logging levels
azure_level = getattr(logging, config.AZURE_PACKAGE_LOGGING_LEVEL.upper(), logging.WARNING)
# Parse comma-separated logging packages
if config.AZURE_LOGGING_PACKAGES:
    packages = [pkg.strip() for pkg in config.AZURE_LOGGING_PACKAGES.split(",") if pkg.strip()]
    for logger_name in packages:
        logging.getLogger(logger_name).setLevel(azure_level)

logging.getLogger("opentelemetry.sdk").setLevel(logging.ERROR)

# Initialize the FastAPI app
app = FastAPI(lifespan=lifespan)
if _ENABLE_OTEL:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError as exc:
        logging.warning(
            "FastAPI OpenTelemetry instrumentation unavailable: %s", exc
        )
    else:
        FastAPIInstrumentor.instrument_app(app)
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
    except ImportError as exc:
        logging.warning("Requests OpenTelemetry instrumentation unavailable: %s", exc)
    else:
        RequestsInstrumentor().instrument()
    try:
        from opentelemetry.instrumentation.urllib import URLLibInstrumentor
    except ImportError as exc:
        logging.warning("urllib OpenTelemetry instrumentation unavailable: %s", exc)
    else:
        URLLibInstrumentor().instrument()
    try:
        from opentelemetry.instrumentation.openai import OpenAIInstrumentor
    except ImportError as exc:
        logging.warning("OpenAI OpenTelemetry instrumentation unavailable: %s", exc)
    else:
        OpenAIInstrumentor().instrument()

def _cors_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    values: list[str] = []
    if raw:
        values.extend([item.strip() for item in raw.split(",") if item.strip()])
    frontend_sites = str(config.FRONTEND_SITE_NAME or "").strip()
    if frontend_sites:
        values.extend([item.strip() for item in frontend_sites.split(",") if item.strip()])

    if str(config.APP_ENV).strip().lower() == "dev":
        values.extend(
            [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped or ["http://localhost:3000"]


frontend_url = config.FRONTEND_SITE_NAME

# Add this near the top of your app.py, after initializing the app
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure health check
app.add_middleware(HealthCheckMiddleware, password="", checks={})
# v4 endpoints
app.include_router(app_v4)
app.include_router(qbo_router)
app.include_router(qbo_api_router)
app.include_router(qbo_data_router)
app.include_router(reviews_router)
app.include_router(drive_router)
logging.info("Added health check middleware")


@app.middleware("http")
async def request_metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logging.exception("Unhandled request error method=%s path=%s", request.method, request.url.path)
        raise

    duration_ms = (time.perf_counter() - started) * 1000
    trace_id = current_trace_id()
    if trace_id:
        response.headers["x-trace-id"] = trace_id
    logging.info(
        "http_request method=%s path=%s status=%s duration_ms=%.2f trace_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        trace_id,
    )
    return response


@app.get("/readyz")
async def readiness_probe():
    return {"status": "ready"}


@app.post("/api/user_browser_language")
async def user_browser_language_endpoint(user_language: UserLanguage, request: Request):
    """
    Receive the user's browser language.

    ---
    tags:
      - User
    parameters:
      - name: language
        in: query
        type: string
        required: true
        description: The user's browser language
    responses:
      200:
        description: Language received successfully
        schema:
          type: object
          properties:
            status:
              type: string
              description: Confirmation message
    """
    config.set_user_local_browser_language(user_language.language)

    # Log the received language for the user
    logging.info(f"Received browser language '{user_language}' for user ")

    return {"status": "Language received successfully"}


# Run the app
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
        access_log=False,
    )
