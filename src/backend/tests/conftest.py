import os
import sys


# Ensure `src/backend` is on sys.path so imports like `import common...` work,
# even when pytest's rootdir is the repository root (repo-level pytest.ini).
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ---------------------------------------------------------------------------
# Stub required env vars so AppConfig() can be instantiated without a live
# Azure environment.  Individual tests should mock any actual network calls.
# os.environ.setdefault() never overwrites values already present (e.g. from
# a .env file or a real CI environment).
# ---------------------------------------------------------------------------
_REQUIRED_STUBS: dict[str, str] = {
    "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=00000000-0000-0000-0000-000000000000",
    "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
    "AZURE_AI_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_AI_RESOURCE_GROUP": "rg-test",
    "AZURE_AI_PROJECT_NAME": "proj-test",
    "AZURE_AI_AGENT_ENDPOINT": "https://test.api.azureml.ms/",
}
for _key, _val in _REQUIRED_STUBS.items():
    os.environ.setdefault(_key, _val)

