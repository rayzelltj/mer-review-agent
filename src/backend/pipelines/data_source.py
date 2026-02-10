from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from common.rules_engine.models import (
    BalanceSheetSnapshot,
    EvidenceBundle,
    ProfitAndLossSnapshot,
    ReconciliationSnapshot,
)


@dataclass(frozen=True)
class ReviewInputs:
    period_end: date
    balance_sheet: BalanceSheetSnapshot
    prior_balance_sheets: tuple[BalanceSheetSnapshot, ...] = ()
    profit_and_loss: ProfitAndLossSnapshot | None = None
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    reconciliations: tuple[ReconciliationSnapshot, ...] = ()


class DataSource(Protocol):
    def build_review_inputs(self, *, client_id: str, period_end: date) -> ReviewInputs:
        """Return canonical inputs for the rules runner."""
        ...

    def save_snapshot(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        """Persist raw snapshot payloads for auditability."""
        ...


def get_data_source(name: str) -> DataSource:
    """Resolve a data source implementation by name (fixtures|live)."""
    source = (name or "").strip().lower()
    if source in ("fixtures", ""):
        return FixturesDataSource()
    if source == "live":
        from .live_qbo import LiveQBODataSource

        return LiveQBODataSource()
    raise ValueError(f"Unknown data source '{name}' (expected 'fixtures' or 'live').")


class FixturesDataSource:
    def __init__(self, *, fixtures_root: Path | None = None) -> None:
        self._fixtures_root = fixtures_root or _default_fixtures_root()

    def build_review_inputs(self, *, client_id: str, period_end: date) -> ReviewInputs:
        from scripts.run_balance_review import build_fixture_review_inputs

        fixtures_dir = self._fixtures_root / client_id / period_end.isoformat()
        return build_fixture_review_inputs(fixtures_dir)

    def save_snapshot(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        return None


def _default_fixtures_root() -> Path:
    return Path(__file__).resolve().parents[2] / "backend" / "tests" / "rules_engine" / "fixtures"
