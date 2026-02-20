from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from common.rules_engine.models import BalanceSheetSnapshot, RuleResult, RuleResultDetail


_STATUS_ORDER = {
    "FAIL": 50,
    "NEEDS_REVIEW": 40,
    "WARN": 30,
    "PASS": 20,
    "NOT_APPLICABLE": 10,
}

_STATUS_PALETTE = {
    "FAIL": "#D13438",
    "NEEDS_REVIEW": "#005A9E",
    "WARN": "#EAA300",
    "PASS": "#107C10",
    "NOT_APPLICABLE": "#605E5C",
}


def build_balance_sheet_view(
    *,
    client_id: str,
    period_end,
    balance_sheet: BalanceSheetSnapshot,
    results: Iterable[RuleResult],
) -> dict[str, Any]:
    accounts = list(balance_sheet.accounts)
    account_by_ref = {acct.account_ref: acct for acct in accounts}
    name_index: dict[str, list[str]] = {}
    for acct in accounts:
        key = _normalize_name(acct.name)
        if not key:
            continue
        name_index.setdefault(key, []).append(acct.account_ref)

    account_hits: dict[str, list[dict[str, Any]]] = {ref: [] for ref in account_by_ref}
    unmapped_findings: list[dict[str, Any]] = []

    for result in results:
        details_by_ref: dict[str, list[RuleResultDetail]] = {}
        unmatched_details: list[RuleResultDetail] = []

        for detail in result.details:
            account_ref = _match_detail_to_account(detail, account_by_ref, name_index)
            if account_ref:
                details_by_ref.setdefault(account_ref, []).append(detail)
            else:
                unmatched_details.append(detail)

        if details_by_ref:
            for account_ref, detail_list in details_by_ref.items():
                account_hits.setdefault(account_ref, []).append(
                    _build_rule_hit(result, detail_list)
                )
            if unmatched_details:
                unmapped_findings.append(_build_rule_hit(result, unmatched_details))
        else:
            unmapped_findings.append(_build_rule_hit(result, list(result.details)))

    account_rows: list[dict[str, Any]] = []
    for acct in accounts:
        hits = account_hits.get(acct.account_ref, [])
        hits_sorted = sorted(hits, key=_rule_hit_sort_key)
        account_rows.append(
            {
                "account": acct.model_dump(mode="json"),
                "status": _worst_status([hit["status"] for hit in hits_sorted]),
                "rule_hits": hits_sorted,
            }
        )

    return {
        "client_id": client_id,
        "period_end": period_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "currency": balance_sheet.currency,
        "status_palette": _STATUS_PALETTE,
        "accounts": account_rows,
        "unmapped_findings": sorted(unmapped_findings, key=_rule_hit_sort_key),
    }


def _normalize_name(value: str) -> str:
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def _match_detail_to_account(
    detail: RuleResultDetail,
    account_by_ref: dict[str, Any],
    name_index: dict[str, list[str]],
) -> str | None:
    key = (detail.key or "").strip()
    if key in account_by_ref:
        return key

    values = detail.values or {}
    for ref_key in ("account_ref", "account_id"):
        ref_val = values.get(ref_key)
        if isinstance(ref_val, str) and ref_val.strip() in account_by_ref:
            return ref_val.strip()

    name_candidates = [
        values.get("account_name"),
        values.get("account_name_fallback"),
        values.get("account"),
        values.get("name"),
        values.get("account_name_match"),
    ]
    for candidate in name_candidates:
        if not isinstance(candidate, str):
            continue
        normalized = _normalize_name(candidate)
        if not normalized:
            continue
        matches = name_index.get(normalized)
        if matches and len(matches) == 1:
            return matches[0]
    return None


def _build_rule_hit(result: RuleResult, details: list[RuleResultDetail]) -> dict[str, Any]:
    detail_statuses = [
        _normalize_status(detail.values.get("status")) for detail in details if detail.values
    ]
    detail_statuses = [status for status in detail_statuses if status]
    status = _worst_status(detail_statuses) if detail_statuses else _normalize_status(result.status)
    severity = _normalize_status(result.severity)
    return {
        "rule_id": result.rule_id,
        "rule_title": result.rule_title,
        "status": status,
        "severity": severity,
        "summary": result.summary,
        "human_action": result.human_action or "",
        "best_practices_reference": result.best_practices_reference,
        "sources": list(result.sources or []),
        "details": [detail.model_dump(mode="json") for detail in details],
        "evidence_used": [item.model_dump(mode="json") for item in result.evidence_used],
    }


def _normalize_status(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _worst_status(statuses: Iterable[str]) -> str:
    values = [status for status in statuses if status]
    if not values:
        return "NOT_APPLICABLE"
    return max(values, key=lambda s: _STATUS_ORDER.get(s, 0))


def _rule_hit_sort_key(hit: dict[str, Any]) -> tuple[int, str]:
    status = hit.get("status") or ""
    return (-_STATUS_ORDER.get(status, 0), str(hit.get("rule_id") or ""))
