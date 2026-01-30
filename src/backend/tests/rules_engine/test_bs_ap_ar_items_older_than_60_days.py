from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_ap_ar_items_older_than_60_days import (
    BS_AP_AR_ITEMS_OLDER_THAN_60_DAYS,
)


def _make_item(name, amount, txn_date):
    return {"name": name, "amount": amount, "txn_date": txn_date}


def test_ap_ar_items_pass_when_none_over_threshold(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": []},
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": [_make_item("Vendor A", "10", "2025-12-01")]},
            ),
            EvidenceItem(
                evidence_type="ar_aging_summary_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": []},
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": [_make_item("Customer A", "5", "2025-12-01")]},
            ),
        ]
    )
    res = BS_AP_AR_ITEMS_OLDER_THAN_60_DAYS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_ap_ar_items_needs_review_when_old_items_present(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="100",
                meta={"items": [{"name": "Vendor A", "amount": "100"}]},
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="100",
                meta={"items": [_make_item("Vendor A", "100", "2025-09-30")]},
            ),
            EvidenceItem(
                evidence_type="ar_aging_summary_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": []},
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": []},
            ),
        ]
    )
    res = BS_AP_AR_ITEMS_OLDER_THAN_60_DAYS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_ap_ar_items_needs_review_when_summary_detail_disagree(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="50",
                meta={"items": [{"name": "Vendor A", "amount": "50"}]},
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="60",
                meta={"items": [_make_item("Vendor A", "60", "2025-09-30")]},
            ),
            EvidenceItem(
                evidence_type="ar_aging_summary_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": []},
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": []},
            ),
        ]
    )
    res = BS_AP_AR_ITEMS_OLDER_THAN_60_DAYS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
    ap_detail = next(d for d in res.details if d.key == "ap_over_60")
    assert ap_detail.values.get("discrepancies")


def test_ap_ar_items_needs_review_when_item_meta_missing(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={},
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={},
            ),
            EvidenceItem(
                evidence_type="ar_aging_summary_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={},
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_over_60",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={},
            ),
        ]
    )
    res = BS_AP_AR_ITEMS_OLDER_THAN_60_DAYS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
