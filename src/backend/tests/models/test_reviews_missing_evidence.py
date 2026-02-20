from __future__ import annotations

from datetime import date, datetime, timezone

from api import reviews
from common.rules_engine.config import ClientRulesConfig
from common.rules_engine.models import EvidenceBundle, RuleResult, RuleRunReport, RuleStatus, Severity


def _report_for(*results: RuleResult) -> RuleRunReport:
    totals = {}
    for result in results:
        totals[result.status] = totals.get(result.status, 0) + 1
    return RuleRunReport(
        run_id="run-test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        period_end=date(2025, 12, 31),
        results=list(results),
        totals=totals,
    )


def test_build_client_rules_config_disables_drive_rules_without_manifest(monkeypatch):
    monkeypatch.setattr(reviews, "is_drive_evidence_enabled", lambda: True)
    monkeypatch.setattr(reviews, "get_drive_manifest_file_id", lambda client_id, user_principal_id=None: "")

    cfg = reviews._build_client_rules_config(client_id="client-1", user_principal_id=None)

    assert set(cfg.rules.keys()) == set(reviews.DRIVE_ONLY_RULE_IDS)
    assert all(cfg.rules[rule_id]["enabled"] is False for rule_id in reviews.DRIVE_ONLY_RULE_IDS)


def test_build_client_rules_config_enables_drive_rules_with_manifest(monkeypatch):
    monkeypatch.setattr(reviews, "is_drive_evidence_enabled", lambda: True)
    monkeypatch.setattr(reviews, "get_drive_manifest_file_id", lambda client_id, user_principal_id=None: "file-123")

    cfg = reviews._build_client_rules_config(client_id="client-1", user_principal_id=None)

    assert cfg.rules == {}


def test_collect_missing_evidence_ignores_deprecated_plooto_instant_field():
    result = RuleResult(
        rule_id="BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE",
        rule_title="Plooto Instant live balance identified",
        best_practices_reference="Plooto",
        sources=["QBO (Balance Sheet)"],
        status=RuleStatus.NEEDS_REVIEW,
        severity=Severity.MEDIUM,
        summary="Plooto Instant account not found in Balance Sheet snapshot; cannot verify.",
    )

    requests = reviews._collect_missing_evidence_requests(
        report=_report_for(result),
        evidence=EvidenceBundle(items=[]),
        client_rules=ClientRulesConfig(rules={}),
    )

    assert requests == []


def test_collect_missing_evidence_includes_drive_requirement_metadata():
    result = RuleResult(
        rule_id="BS-LOAN-BALANCE-MATCH",
        rule_title="Loan balance tallied to loan schedule",
        best_practices_reference="Loans",
        sources=["Google Drive (loan schedule)", "QBO (Balance Sheet)"],
        status=RuleStatus.NEEDS_REVIEW,
        severity=Severity.MEDIUM,
        summary="Loan balance needs schedule evidence to verify.",
    )

    requests = reviews._collect_missing_evidence_requests(
        report=_report_for(result),
        evidence=EvidenceBundle(items=[]),
        client_rules=ClientRulesConfig(rules={}),
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.rule_id == "BS-LOAN-BALANCE-MATCH"
    assert request.evidence_type == "loan_schedule_balance"
    assert request.suggested_source == "Drive"
    assert request.required_document is not None
    assert "Loan schedule" in request.required_document
    assert request.adapter_hint is not None


def test_collect_missing_evidence_includes_multiple_qbo_requirements():
    result = RuleResult(
        rule_id="BS-AP-SUBLEDGER-RECONCILES",
        rule_title="Aged Payables Detail reconciles to Balance Sheet",
        best_practices_reference="Accounts Payable/Receivable",
        sources=["QBO"],
        status=RuleStatus.NEEDS_REVIEW,
        severity=Severity.MEDIUM,
        summary="Missing AP aging evidence.",
    )

    requests = reviews._collect_missing_evidence_requests(
        report=_report_for(result),
        evidence=EvidenceBundle(items=[]),
        client_rules=ClientRulesConfig(rules={}),
    )

    assert {request.evidence_type for request in requests} == {
        "ap_aging_summary_total",
        "ap_aging_detail_total",
    }
    assert all(request.suggested_source == "QBO" for request in requests)
