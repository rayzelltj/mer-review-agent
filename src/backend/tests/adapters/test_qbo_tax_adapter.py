import json
from pathlib import Path

from adapters.qbo.tax import (
    tax_agencies_to_evidence,
    tax_payments_to_evidence,
    tax_returns_to_evidence,
)


def test_tax_adapters_parse_blackbird_fixture():
    base = (
        Path(__file__).parents[2]
        / "tests/rules_engine/fixtures/blackbird_fabrics/2025-12-31"
    )
    agencies = json.load((base / "tax_agencies.json").open())
    returns = json.load((base / "tax_returns.json").open())
    payments = json.load((base / "tax_payments.json").open())

    agencies_item = tax_agencies_to_evidence(agencies)
    returns_item = tax_returns_to_evidence(returns)
    payments_item = tax_payments_to_evidence(payments)

    assert agencies_item.evidence_type == "tax_agencies"
    assert returns_item.evidence_type == "tax_returns"
    assert payments_item.evidence_type == "tax_payments"
    assert len(agencies_item.meta["items"]) >= 1
    assert len(returns_item.meta["items"]) >= 1
    assert len(payments_item.meta["items"]) >= 1
