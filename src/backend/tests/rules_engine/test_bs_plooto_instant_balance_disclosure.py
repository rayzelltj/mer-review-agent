from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_plooto_instant_balance_disclosure import (
    BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE,
)


def test_plooto_instant_pass_when_balances_match_and_zero(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {
        "BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {
            "account_ref": "P1",
            "account_name": "Plooto Instant",
            "evidence_type": "plooto_instant_live_balance",
            "require_evidence_as_of_date_match_period_end": True,
        }
    }
    bs = make_balance_sheet(
        accounts=[{"account_ref": "P1", "name": "Plooto Instant", "type": "Other Current Asset", "balance": "0"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="plooto_instant_live_balance",
                source="fixture",
                as_of_date=period_end,
                amount="0",
            )
        ]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_plooto_instant_fail_when_non_zero_even_if_matches(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {"account_ref": "P1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "P1", "name": "Plooto Instant", "type": "Other Current Asset", "balance": "25"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="plooto_instant_live_balance",
                source="fixture",
                as_of_date=period_end,
                amount="25",
            )
        ]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH


def test_plooto_instant_fail_when_mismatch(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {"account_ref": "P1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "P1", "name": "Plooto Instant", "type": "Other Current Asset", "balance": "10"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="plooto_instant_live_balance",
                source="fixture",
                as_of_date=period_end,
                amount="11",
            )
        ]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL


def test_plooto_instant_needs_review_when_evidence_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {"account_ref": "P1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "P1", "name": "Plooto Instant", "type": "Other Current Asset", "balance": "0"}]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, evidence=EvidenceBundle(items=[]), client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_plooto_instant_needs_review_when_evidence_date_mismatch(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {"account_ref": "P1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "P1", "name": "Plooto Instant", "type": "Other Current Asset", "balance": "0"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="plooto_instant_live_balance",
                source="fixture",
                as_of_date=date(2025, 12, 30),
                amount="0",
            )
        ]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_plooto_instant_needs_review_when_balance_sheet_account_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {"account_ref": "P1"}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="plooto_instant_live_balance",
                source="fixture",
                as_of_date=date(2025, 12, 31),
                amount="0",
            )
        ]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW

