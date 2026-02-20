from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Iterable

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from common.rules_engine.models import RuleRunReport

LOGGER = logging.getLogger(__name__)
_OPENAI_CLIENT: AzureOpenAI | None = None
_STATUS_ORDER = {"FAIL": 50, "NEEDS_REVIEW": 40, "WARN": 30, "PASS": 20, "NOT_APPLICABLE": 10}


def generate_balance_sheet_summary(
    *,
    client_id: str,
    period_end: date,
    report: RuleRunReport,
    notes: str | None = None,
    balance_sheet_view: dict[str, Any] | None = None,
) -> str:
    payload = {
        "client_id": client_id,
        "period_end": period_end.isoformat(),
        "totals": _totals_payload(report),
        "notes": notes or "",
        "findings": _compact_findings(report),
        "report_rows": _build_report_rows(balance_sheet_view),
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are an internal accounting review assistant. Produce a concise markdown report.\n"
                "Required sections:\n"
                "1) Executive Summary (3-6 sentences)\n"
                "2) Findings by Status (bullet list)\n"
                "3) Detailed Review Table with columns: Balance Sheet Item | Status | Evidence/Why Flagged | Required Action\n"
                "Rules:\n"
                "- Prioritize FAIL and NEEDS_REVIEW items.\n"
                "- Use only facts from the input payload.\n"
                "- If evidence is missing, state it explicitly.\n"
                "- Keep table rows focused and audit-ready."
            ),
        },
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]

    try:
        client = _get_openai_client()
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1").strip()
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=0,
            top_p=1,
            max_tokens=900,
        )
        content = response.choices[0].message.content if response.choices else ""
        return (content or "").strip() or _fallback_summary(
            client_id,
            period_end,
            report,
            balance_sheet_view=balance_sheet_view,
        )
    except Exception as exc:
        LOGGER.warning("Summary generation failed: %s", exc)
        return _fallback_summary(
            client_id,
            period_end,
            report,
            balance_sheet_view=balance_sheet_view,
        )


def _get_openai_client() -> AzureOpenAI:
    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is not None:
        return _OPENAI_CLIENT

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-11-20").strip()
    if not endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is required for summary generation.")

    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    if api_key:
        _OPENAI_CLIENT = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        return _OPENAI_CLIENT

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    _OPENAI_CLIENT = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=api_version,
    )
    return _OPENAI_CLIENT


def _compact_findings(report: RuleRunReport) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for result in report.results:
        status = getattr(result.status, "value", result.status)
        severity = getattr(result.severity, "value", result.severity)
        findings.append(
            {
                "rule_id": result.rule_id,
                "status": status,
                "severity": severity,
                "summary": result.summary,
                "human_action": result.human_action or "",
            }
        )
    return findings


def _totals_payload(report: RuleRunReport) -> dict[str, int]:
    totals: dict[str, int] = {}
    for status, count in report.totals.items():
        key = getattr(status, "value", status)
        totals[str(key)] = int(count)
    return totals


def _build_report_rows(balance_sheet_view: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(balance_sheet_view, dict):
        return []

    accounts = balance_sheet_view.get("accounts") or []
    rows: list[dict[str, str]] = []
    for account_row in accounts:
        if not isinstance(account_row, dict):
            continue
        status = str(account_row.get("status") or "NOT_APPLICABLE")
        if status in {"PASS", "NOT_APPLICABLE"}:
            continue

        account = account_row.get("account") or {}
        account_name = str(account.get("name") or account.get("account_ref") or "Unknown account")
        hits = account_row.get("rule_hits") or []
        if not isinstance(hits, list):
            hits = []

        if hits:
            hit = hits[0] if isinstance(hits[0], dict) else {}
            detail_text = str(hit.get("summary") or "Flagged during review.")
            action = str(hit.get("human_action") or "Investigate and reconcile this item.")
            rule_id = str(hit.get("rule_id") or "")
            if rule_id:
                detail_text = f"{rule_id}: {detail_text}"
        else:
            detail_text = "Flagged during review."
            action = "Investigate and reconcile this item."

        rows.append(
            {
                "balance_sheet_item": account_name,
                "status": status,
                "evidence_or_reason": detail_text,
                "required_action": action,
            }
        )

    rows.sort(key=lambda row: _STATUS_ORDER.get(row["status"], 0), reverse=True)
    return rows[:20]


def _table_lines(rows: Iterable[dict[str, str]]) -> list[str]:
    lines = [
        "| Balance Sheet Item | Status | Evidence/Why Flagged | Required Action |",
        "|---|---|---|---|",
    ]
    for row in rows:
        item = _md_escape(row.get("balance_sheet_item", ""))
        status = _md_escape(row.get("status", ""))
        evidence = _md_escape(row.get("evidence_or_reason", ""))
        action = _md_escape(row.get("required_action", ""))
        lines.append(f"| {item} | {status} | {evidence} | {action} |")
    return lines


def _md_escape(value: str) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned.replace("|", "\\|")


def _fallback_summary(
    client_id: str,
    period_end: date,
    report: RuleRunReport,
    *,
    balance_sheet_view: dict[str, Any] | None = None,
) -> str:
    totals = _totals_payload(report)
    totals_lines = "\n".join(f"- {status}: {count}" for status, count in totals.items())
    rows = _build_report_rows(balance_sheet_view)

    summary_lines = [
        f"### Executive Summary",
        (
            f"Balance sheet review for **{client_id}** as of **{period_end.isoformat()}** "
            "completed. The table below highlights the accounts with exceptions or missing evidence."
        ),
        "",
        "### Findings by Status",
        totals_lines or "- No totals available.",
        "",
        "### Detailed Review Table",
    ]
    if rows:
        summary_lines.extend(_table_lines(rows))
    else:
        summary_lines.append("No failing or review-required balance sheet rows were available.")
    return "\n".join(summary_lines)
