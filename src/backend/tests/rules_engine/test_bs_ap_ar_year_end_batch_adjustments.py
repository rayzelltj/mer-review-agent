from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_ap_ar_year_end_batch_adjustments import (
    BS_AP_AR_YEAR_END_BATCH_ADJUSTMENTS,
)


def test_year_end_batch_adjustments_pass_when_no_generic_names(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-YEAR_END_BATCH_ADJUSTMENTS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="10",
                meta={"items": [{"name": "Vendor A", "open_balance": "10"}]},
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="20",
                meta={"items": [{"name": "Customer A", "open_balance": "20"}]},
            ),
        ]
    )
    res = BS_AP_AR_YEAR_END_BATCH_ADJUSTMENTS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_year_end_batch_adjustments_needs_review_when_generic_names(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-YEAR_END_BATCH_ADJUSTMENTS": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="10",
                meta={"items": [{"name": "YE Adj 24 CAD", "open_balance": "10"}]},
            ),
            EvidenceItem(
                evidence_type="ar_aging_detail_rows",
                source="fixture",
                as_of_date=period_end,
                amount="20",
                meta={"items": [{"name": "Year-end Review", "open_balance": "20"}]},
            ),
        ]
    )
    res = BS_AP_AR_YEAR_END_BATCH_ADJUSTMENTS().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_year_end_batch_adjustments_not_applicable_when_no_evidence(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-AP-AR-YEAR_END_BATCH_ADJUSTMENTS": {}}
    bs = make_balance_sheet(accounts=[])
    res = BS_AP_AR_YEAR_END_BATCH_ADJUSTMENTS().evaluate(
        make_ctx(balance_sheet=bs, evidence=EvidenceBundle(items=[]), client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NOT_APPLICABLE
