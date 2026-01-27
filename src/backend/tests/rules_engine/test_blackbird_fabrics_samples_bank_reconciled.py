import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from common.rules_engine.context import RuleContext
from common.rules_engine.models import BalanceSheetSnapshot, EvidenceBundle, EvidenceItem, ReconciliationSnapshot, RuleStatus
from common.rules_engine.config import ClientRulesConfig
from common.rules_engine.rules.bs_bank_reconciled_through_period_end import (
    BS_BANK_RECONCILED_THROUGH_PERIOD_END,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "blackbird_fabrics" / "2025-11-30"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _account_ref_from_name(name: str) -> str:
    # Test-only adapter shim: report samples do not include stable IDs, so we key on account name.
    return f"name::{name}"


def test_blackbird_paypal_aud_reconciliation_matches_attachment():
    period_end = date(2025, 11, 30)
    rec_report = _load_json("reconciliation_report_paypal_aud.json")
    attachment = _load_json("attachment_paypal_activity_statement.json")

    account_name = rec_report["account"]["name"]
    account_ref = _account_ref_from_name(account_name)

    statement_end = date.fromisoformat(rec_report["period"]["ending"])
    statement_ending_balance = Decimal(rec_report["summary"]["statement_ending_balance"])

    # Attachment has multiple currencies; pick the AUD ending balance (adapter responsibility).
    aud_row = next(r for r in attachment["balance_summary"]["rows"] if r["currency"] == "AUD")
    attachment_amount = Decimal(aud_row["available_ending"])

    bs = BalanceSheetSnapshot(
        as_of_date=period_end,
        accounts=[
            {
                "account_ref": account_ref,
                "name": account_name,
                "type": "Bank",
                "balance": str(statement_ending_balance),
            }
        ],
    )

    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=statement_end,
                amount=str(attachment_amount),
                uri="fixture://paypal_activity_statement",
                meta={"account_ref": account_ref, "currency": "AUD"},
            )
        ]
    )

    recs = (
        ReconciliationSnapshot(
            account_ref=account_ref,
            account_name=account_name,
            statement_end_date=statement_end,
            statement_ending_balance=str(statement_ending_balance),
            book_balance_as_of_statement_end=str(statement_ending_balance),
            book_balance_as_of_period_end=str(statement_ending_balance),
            source="fixture",
        ),
    )

    cfg = ClientRulesConfig(
        rules={
            "BS-BANK-RECONCILED-THROUGH-PERIOD-END": {
                "expected_accounts": [account_ref],
                "require_statement_balance_matches_attachment": True,
                "statement_balance_attachment_evidence_type": "statement_balance_attachment",
                "require_book_balance_as_of_period_end_ties_to_balance_sheet": True,
                # NOTE: real QBO multi-currency requires adapter-provided, currency-consistent amounts.
                "require_statement_balance_matches_balance_sheet": True,
            }
        }
    )

    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        RuleContext(
            period_end=period_end,
            balance_sheet=bs,
            evidence=evidence,
            reconciliations=recs,
            client_config=cfg,
        )
    )
    assert res.status == RuleStatus.PASS
    assert res.details and res.details[0].values.get("attachment_status") == RuleStatus.PASS.value


def test_blackbird_paypal_cad_reconciliation_matches_attachment():
    period_end = date(2025, 11, 30)
    rec_report = _load_json("reconciliation_report_paypal_cad.json")
    attachment = _load_json("attachment_paypal_activity_statement.json")

    account_name = rec_report["account"]["name"]
    account_ref = _account_ref_from_name(account_name)

    statement_end = date.fromisoformat(rec_report["period"]["ending"])
    statement_ending_balance = Decimal(rec_report["summary"]["statement_ending_balance"])

    cad_row = next(r for r in attachment["balance_summary"]["rows"] if r["currency"] == "CAD")
    attachment_amount = Decimal(cad_row["available_ending"])

    bs = BalanceSheetSnapshot(
        as_of_date=period_end,
        accounts=[
            {
                "account_ref": account_ref,
                "name": account_name,
                "type": "Bank",
                "balance": str(statement_ending_balance),
            }
        ],
    )

    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=statement_end,
                amount=str(attachment_amount),
                uri="fixture://paypal_activity_statement",
                meta={"account_ref": account_ref, "currency": "CAD"},
            )
        ]
    )

    recs = (
        ReconciliationSnapshot(
            account_ref=account_ref,
            account_name=account_name,
            statement_end_date=statement_end,
            statement_ending_balance=str(statement_ending_balance),
            book_balance_as_of_statement_end=str(statement_ending_balance),
            book_balance_as_of_period_end=str(statement_ending_balance),
            source="fixture",
        ),
    )

    cfg = ClientRulesConfig(
        rules={
            "BS-BANK-RECONCILED-THROUGH-PERIOD-END": {
                "expected_accounts": [account_ref],
                "require_statement_balance_matches_attachment": True,
                "statement_balance_attachment_evidence_type": "statement_balance_attachment",
                "require_book_balance_as_of_period_end_ties_to_balance_sheet": True,
                "require_statement_balance_matches_balance_sheet": True,
            }
        }
    )

    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        RuleContext(
            period_end=period_end,
            balance_sheet=bs,
            evidence=evidence,
            reconciliations=recs,
            client_config=cfg,
        )
    )
    assert res.status == RuleStatus.PASS
    assert res.details and res.details[0].values.get("attachment_status") == RuleStatus.PASS.value


def test_blackbird_attachment_mismatch_fails():
    period_end = date(2025, 11, 30)
    rec_report = _load_json("reconciliation_report_paypal_aud.json")

    account_name = rec_report["account"]["name"]
    account_ref = _account_ref_from_name(account_name)

    statement_end = date.fromisoformat(rec_report["period"]["ending"])
    statement_ending_balance = Decimal(rec_report["summary"]["statement_ending_balance"])

    bs = BalanceSheetSnapshot(
        as_of_date=period_end,
        accounts=[
            {
                "account_ref": account_ref,
                "name": account_name,
                "type": "Bank",
                "balance": str(statement_ending_balance),
            }
        ],
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=statement_end,
                amount=str(statement_ending_balance - Decimal("0.01")),
                meta={"account_ref": account_ref},
            )
        ]
    )
    recs = (
        ReconciliationSnapshot(
            account_ref=account_ref,
            account_name=account_name,
            statement_end_date=statement_end,
            statement_ending_balance=str(statement_ending_balance),
            book_balance_as_of_statement_end=str(statement_ending_balance),
            book_balance_as_of_period_end=str(statement_ending_balance),
            source="fixture",
        ),
    )
    cfg = ClientRulesConfig(
        rules={
            "BS-BANK-RECONCILED-THROUGH-PERIOD-END": {
                "expected_accounts": [account_ref],
                "require_statement_balance_matches_attachment": True,
            }
        }
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        RuleContext(
            period_end=period_end,
            balance_sheet=bs,
            evidence=evidence,
            reconciliations=recs,
            client_config=cfg,
        )
    )
    assert res.status == RuleStatus.FAIL
