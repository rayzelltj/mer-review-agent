from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_ap_ar_negative_open_items import (
    BS_AP_AR_NEGATIVE_OPEN_ITEMS,
)


def test_ap_ar_negative_open_items_pass_when_none_negative(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-NEGATIVE-OPEN-ITEMS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="100",
                meta={"items": [{"name": "Vendor A", "open_balance": "10.00"}]},
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="200",
                meta={"items": [{"name": "Customer A", "open_balance": "20.00"}]},
            ),
        ]
    )
    res = BS_AP_AR_NEGATIVE_OPEN_ITEMS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_ap_ar_negative_open_items_needs_review_when_negative(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-NEGATIVE-OPEN-ITEMS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="100",
                meta={"items": [{"name": "Vendor A", "open_balance": "-10.00"}]},
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="200",
                meta={"items": [{"name": "Customer A", "open_balance": "20.00"}]},
            ),
        ]
    )
    res = BS_AP_AR_NEGATIVE_OPEN_ITEMS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_ap_ar_negative_open_items_needs_review_when_evidence_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-AP-AR-NEGATIVE-OPEN-ITEMS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(items=[])
    res = BS_AP_AR_NEGATIVE_OPEN_ITEMS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
