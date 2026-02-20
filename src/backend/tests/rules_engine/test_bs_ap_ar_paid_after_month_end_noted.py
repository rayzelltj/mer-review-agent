from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_ap_ar_paid_after_month_end_noted import (
    BS_AP_AR_PAID_AFTER_MONTH_END_NOTED,
)


def _rows(*items):
    return {"items": list(items)}


def test_paid_after_month_end_needs_review_when_settled_items_found(
    make_balance_sheet, make_ctx, period_end
):
    rule_cfg = {"BS-AP-AR-PAID-AFTER-MONTH-END-NOTED": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="150",
                meta=_rows(
                    {"id": "A-1", "name": "Vendor A", "open_balance": "100.00"},
                    {"id": "A-2", "name": "Vendor B", "open_balance": "50.00"},
                ),
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 18),
                amount="50",
                meta=_rows({"id": "A-2", "name": "Vendor B", "open_balance": "50.00"}),
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="80",
                meta=_rows({"id": "R-1", "name": "Customer A", "open_balance": "80.00"}),
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 18),
                amount="80",
                meta=_rows({"id": "R-1", "name": "Customer A", "open_balance": "80.00"}),
            ),
        ]
    )

    res = BS_AP_AR_PAID_AFTER_MONTH_END_NOTED().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )

    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.severity == Severity.MEDIUM
    assert "settled after 2025-12-31" in res.summary
    ap_detail = next(d for d in res.details if d.key == "ap_paid_after_month_end")
    assert ap_detail.values["settled_count"] == 1
    assert "2026-01-18" in ap_detail.values["settled_items"][0]["note"]


def test_paid_after_month_end_pass_when_no_settled_items(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-PAID-AFTER-MONTH-END-NOTED": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="100",
                meta=_rows({"id": "A-1", "name": "Vendor A", "open_balance": "100.00"}),
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 18),
                amount="100",
                meta=_rows({"id": "A-1", "name": "Vendor A", "open_balance": "100.00"}),
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="75",
                meta=_rows({"id": "R-1", "name": "Customer A", "open_balance": "75.00"}),
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 18),
                amount="75",
                meta=_rows({"id": "R-1", "name": "Customer A", "open_balance": "75.00"}),
            ),
        ]
    )

    res = BS_AP_AR_PAID_AFTER_MONTH_END_NOTED().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_paid_after_month_end_needs_review_when_follow_up_missing(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-PAID-AFTER-MONTH-END-NOTED": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="100",
                meta=_rows({"id": "A-1", "name": "Vendor A", "open_balance": "100.00"}),
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="75",
                meta=_rows({"id": "R-1", "name": "Customer A", "open_balance": "75.00"}),
            ),
        ]
    )

    res = BS_AP_AR_PAID_AFTER_MONTH_END_NOTED().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert "Missing AP/AR follow-up aging detail evidence" in res.summary


def test_paid_after_month_end_not_applicable_without_period_end_snapshots(
    make_balance_sheet, make_ctx
):
    rule_cfg = {"BS-AP-AR-PAID-AFTER-MONTH-END-NOTED": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 18),
                amount="20",
                meta=_rows({"id": "A-1", "name": "Vendor A", "open_balance": "20.00"}),
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 18),
                amount="20",
                meta=_rows({"id": "R-1", "name": "Customer A", "open_balance": "20.00"}),
            ),
        ]
    )

    res = BS_AP_AR_PAID_AFTER_MONTH_END_NOTED().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NOT_APPLICABLE


def test_paid_after_month_end_respects_explicit_comparison_date(
    make_balance_sheet, make_ctx, period_end
):
    rule_cfg = {
        "BS-AP-AR-PAID-AFTER-MONTH-END-NOTED": {
            "comparison_as_of_date": "2026-01-18",
        }
    }
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="100",
                meta=_rows({"id": "A-1", "name": "Vendor A", "open_balance": "100.00"}),
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 18),
                amount="100",
                meta=_rows({"id": "A-1", "name": "Vendor A", "open_balance": "100.00"}),
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 25),
                amount="0",
                meta=_rows(),
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="50",
                meta=_rows({"id": "R-1", "name": "Customer A", "open_balance": "50.00"}),
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=date(2026, 1, 18),
                amount="50",
                meta=_rows({"id": "R-1", "name": "Customer A", "open_balance": "50.00"}),
            ),
        ]
    )

    res = BS_AP_AR_PAID_AFTER_MONTH_END_NOTED().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
