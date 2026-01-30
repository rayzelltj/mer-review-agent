from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_ap_subledger_reconciles import BS_AP_SUBLEDGER_RECONCILES


def test_ap_subledger_pass_when_totals_match(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-SUBLEDGER-RECONCILES": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "AP1", "name": "Accounts Payable (A/P)", "type": "Liability", "balance": "40000"},
            {"account_ref": "AP2", "name": "Accounts Payable (A/P) - USD", "type": "Liability", "balance": "5000"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_total",
                source="fixture",
                as_of_date=period_end,
                amount="45000",
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_total",
                source="fixture",
                as_of_date=period_end,
                amount="45000",
            ),
        ]
    )
    res = BS_AP_SUBLEDGER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_ap_subledger_prefers_total_line_when_present(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-SUBLEDGER-RECONCILES": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "AP1", "name": "Accounts Payable (A/P)", "type": "Liability", "balance": "40000"},
            {"account_ref": "AP2", "name": "Accounts Payable (A/P) - USD", "type": "Liability", "balance": "5000"},
            {"account_ref": "report::Total Accounts Payable (A/P)", "name": "Total Accounts Payable (A/P)", "type": "", "balance": "45000"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_total",
                source="fixture",
                as_of_date=period_end,
                amount="45000",
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_total",
                source="fixture",
                as_of_date=period_end,
                amount="45000",
            ),
        ]
    )
    res = BS_AP_SUBLEDGER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.details[0].values.get("used_total_line") is True


def test_ap_subledger_fail_when_summary_mismatch(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-SUBLEDGER-RECONCILES": {}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "AP1", "name": "Accounts Payable", "type": "Liability", "balance": "1000"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_total",
                source="fixture",
                as_of_date=period_end,
                amount="900",
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_total",
                source="fixture",
                as_of_date=period_end,
                amount="1000",
            ),
        ]
    )
    res = BS_AP_SUBLEDGER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL


def test_ap_subledger_fail_when_detail_mismatch(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-SUBLEDGER-RECONCILES": {}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "AP1", "name": "Accounts Payable", "type": "Liability", "balance": "1000"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_total",
                source="fixture",
                as_of_date=period_end,
                amount="1000",
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_total",
                source="fixture",
                as_of_date=period_end,
                amount="1100",
            ),
        ]
    )
    res = BS_AP_SUBLEDGER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL


def test_ap_subledger_needs_review_when_summary_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-AP-SUBLEDGER-RECONCILES": {}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "AP1", "name": "Accounts Payable", "type": "Liability", "balance": "1000"}]
    )
    evidence = EvidenceBundle(items=[])
    res = BS_AP_SUBLEDGER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_ap_subledger_needs_review_when_date_mismatch(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-AP-SUBLEDGER-RECONCILES": {}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "AP1", "name": "Accounts Payable", "type": "Liability", "balance": "1000"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_total",
                source="fixture",
                as_of_date=date(2025, 12, 30),
                amount="1000",
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_total",
                source="fixture",
                as_of_date=date(2025, 12, 31),
                amount="1000",
            ),
        ]
    )
    res = BS_AP_SUBLEDGER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_ap_subledger_not_applicable_when_no_accounts(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-SUBLEDGER-RECONCILES": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="ap_aging_summary_total",
                source="fixture",
                as_of_date=period_end,
                amount="0",
            ),
            EvidenceItem(
                evidence_type="ap_aging_detail_total",
                source="fixture",
                as_of_date=period_end,
                amount="0",
            ),
        ]
    )
    res = BS_AP_SUBLEDGER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NOT_APPLICABLE
