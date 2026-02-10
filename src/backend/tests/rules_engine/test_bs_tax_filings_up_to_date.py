import json
from datetime import date
from pathlib import Path

from common.rules_engine.context import RuleContext
from common.rules_engine.models import EvidenceBundle, RuleStatus
from common.rules_engine.rules.bs_tax_filings_up_to_date import (
    BS_TAX_FILINGS_UP_TO_DATE,
    _add_months,
    _expected_period_end,
)
from adapters.qbo.tax import tax_agencies_to_evidence, tax_returns_to_evidence


def test_tax_filings_up_to_date_blackbird(period_end, make_balance_sheet):
    base = (
        Path(__file__).parents[2]
        / "tests/rules_engine/fixtures/blackbird_fabrics/2025-12-31"
    )
    agencies = json.load((base / "tax_agencies.json").open())
    returns = json.load((base / "tax_returns.json").open())

    evidence = EvidenceBundle(
        items=[tax_agencies_to_evidence(agencies), tax_returns_to_evidence(returns)]
    )
    ctx = RuleContext(
        period_end=period_end,
        balance_sheet=make_balance_sheet(accounts=[]),
        evidence=evidence,
    )

    result = BS_TAX_FILINGS_UP_TO_DATE().evaluate(ctx)
    assert result.status == RuleStatus.PASS


def test_tax_filing_expected_period_end_quarterly():
    anchor = date(2025, 10, 31)
    assert _expected_period_end(date(2025, 12, 31), 3, anchor) == date(2025, 10, 31)
    assert _expected_period_end(date(2026, 1, 31), 3, anchor) == date(2026, 1, 31)


def test_add_months_preserves_month_end():
    assert _add_months(date(2026, 1, 31), 3) == date(2026, 4, 30)
