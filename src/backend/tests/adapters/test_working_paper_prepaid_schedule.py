from datetime import date
from decimal import Decimal
from pathlib import Path

from adapters.working_papers.prepaid_schedule import prepaid_schedule_to_evidence


def test_prepaid_schedule_extracts_eom_balance():
    fixture = Path(
        "src/backend/tests/rules_engine/fixtures/blackbird_fabrics/2025-11-30/"
        "Blackbird Fabrics _ Prepaid Schedule - Prepaid.csv"
    )
    evidence = prepaid_schedule_to_evidence(fixture, period_end=date(2025, 11, 30))

    assert evidence.evidence_type == "working_paper_balance"
    assert evidence.as_of_date == date(2025, 11, 30)
    assert evidence.amount == Decimal("6978.74")
