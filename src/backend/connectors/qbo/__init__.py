"""QBO connector stubs (network + auth lives here; adapters live in src/backend/adapters/qbo)."""

from .config import QBOConfig, get_qbo_config
from .sync import build_snapshots

__all__ = ["QBOConfig", "get_qbo_config", "build_snapshots"]
