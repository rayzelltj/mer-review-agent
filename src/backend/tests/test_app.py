import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock Azure dependencies to prevent import errors
sys.modules["azure.monitor"] = MagicMock()
sys.modules["azure.monitor.events.extension"] = MagicMock()
sys.modules["azure.monitor.opentelemetry"] = MagicMock()
sys.modules["azure.ai.projects"] = MagicMock()
sys.modules["azure.ai.projects.models"] = MagicMock()
sys.modules["azure.ai.projects.aio"] = MagicMock()

# Mock environment variables before importing app
os.environ["COSMOSDB_ENDPOINT"] = "https://mock-endpoint"
os.environ["COSMOSDB_KEY"] = "mock-key"
os.environ["COSMOSDB_DATABASE"] = "mock-database"
os.environ["COSMOSDB_CONTAINER"] = "mock-container"
os.environ[
    "APPLICATIONINSIGHTS_CONNECTION_STRING"
] = "InstrumentationKey=mock-instrumentation-key;IngestionEndpoint=https://mock-ingestion-endpoint"
os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"] = "mock-deployment-name"
os.environ["AZURE_OPENAI_API_VERSION"] = "2023-01-01"
os.environ["AZURE_OPENAI_ENDPOINT"] = "https://mock-openai-endpoint"

# Ensure repo root is on sys.path so `src.backend...` imports work
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Provide safe defaults for vars that app_config reads at import-time
os.environ.setdefault("AZURE_AI_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("AZURE_AI_RESOURCE_GROUP", "rg-test")
os.environ.setdefault("AZURE_AI_PROJECT_NAME", "proj-test")
os.environ.setdefault("AZURE_AI_AGENT_ENDPOINT", "https://agents.example.com/")
os.environ.setdefault("USER_LOCAL_BROWSER_LANGUAGE", "en-US")

# Mock telemetry initialization to prevent errors
with patch("azure.monitor.opentelemetry.configure_azure_monitor", MagicMock()):
    try:
        from src.backend.app import app  # preferred if file exists
    except ModuleNotFoundError:
        # fallback to app which exists in this repo
        import importlib
        mod = importlib.import_module("src.backend.app")
        app = getattr(mod, "app", None)
        if app is None:
            create_app = getattr(mod, "create_app", None)
            if create_app is not None:
                app = create_app()
            else:
                raise

# Initialize FastAPI test client
client = TestClient(app)

from fastapi.routing import APIRoute


def test_readyz_endpoint():
    """Test the health check endpoint returns 200."""
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"


def test_root_returns_404():
    """Test that the root endpoint is not defined."""
    response = client.get("/")
    assert response.status_code == 404


def test_v4_router_mounted():
    """Test that the /api/v4 router is mounted and discoverable."""
    route_paths = [r.path for r in app.routes if isinstance(r, APIRoute)]
    v4_paths = [p for p in route_paths if p.startswith("/api/v4")]
    assert len(v4_paths) > 0, "No /api/v4 routes found"
    assert "/api/v4/process_request" in v4_paths


def test_process_request_requires_auth():
    """Test that /api/v4/process_request rejects unauthenticated requests."""
    test_input = {
        "session_id": "test-session-123",
        "description": "Create a marketing plan",
    }
    response = client.post("/api/v4/process_request", json=test_input)
    # Should fail due to missing/invalid auth
    assert response.status_code in (400, 401, 403, 500)


def test_user_browser_language_endpoint():
    """Test the /api/user_browser_language endpoint."""
    response = client.post(
        "/api/user_browser_language",
        json={"language": "en-US"},
    )
    assert response.status_code == 200


if __name__ == "__main__":
    pytest.main()
