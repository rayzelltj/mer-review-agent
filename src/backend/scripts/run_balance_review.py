from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def _ensure_backend_on_path() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


def _load_json(path: Path):
    with path.open() as handle:
        return json.load(handle)

def _load_optional_json(path: Path):
    if not path.exists():
        return None
    return _load_json(path)


def _parse_report_period(report: dict) -> date | None:
    header = report.get("Header")
    if not isinstance(header, dict):
        return None
    end_period = header.get("EndPeriod")
    if isinstance(end_period, str) and end_period.strip():
        try:
            return date.fromisoformat(end_period.strip())
        except ValueError:
            return None
    return None


def _load_prior_balance_sheet_reports(
    fixtures_dir: Path,
    current_period: date,
    *,
    count: int = 3,
) -> list[tuple[date, dict]]:
    parent = fixtures_dir.parent
    if not parent.exists():
        return []
    candidates: list[tuple[date, dict]] = []
    for child in parent.iterdir():
        if not child.is_dir() or child == fixtures_dir:
            continue
        report_path = child / "balance_sheet.json"
        if not report_path.exists():
            continue
        try:
            report = _load_json(report_path)
        except Exception:
            continue
        period = _parse_report_period(report)
        if period and period < current_period:
            candidates.append((period, report))
    candidates.sort(key=lambda item: item[0])
    if count:
        candidates = candidates[-count:]
    return candidates


def _write_markdown(report, out_path: Path) -> None:
    lines = [
        f"# Balance Review {report.period_end}",
        "",
        f"Generated at: {report.generated_at.isoformat()}",
        "",
        "## Totals",
    ]
    for status, count in report.totals.items():
        lines.append(f"- {status}: {count}")
    lines.append("")
    lines.append("## Results")
    for res in report.results:
        lines.append("")
        lines.append(f"### {res.rule_id} — {res.status}")
        lines.append(res.rule_title)
        if res.summary:
            lines.append(f"- Summary: {res.summary}")
        if res.best_practices_reference:
            lines.append(f"- Reference: {res.best_practices_reference}")
        if res.sources:
            lines.append(f"- Sources: {', '.join(res.sources)}")
        if res.human_action:
            lines.append(f"- Action: {res.human_action}")
        if res.details:
            lines.append("- Details:")
            for detail in res.details:
                lines.append(f"  - {detail.key}: {detail.message} | {detail.values}")
        if res.evidence_used:
            lines.append("- Evidence:")
            for ev in res.evidence_used:
                lines.append(
                    f"  - {ev.evidence_type} (amount={ev.amount}, as_of={ev.as_of_date}, source={ev.source})"
                )
    out_path.write_text("\n".join(lines))


def _normalize_status(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(getattr(value, "value"))
    text = str(value)
    if text.startswith("RuleStatus."):
        return text.split("RuleStatus.", 1)[1]
    return text


def _collect_review_comments(report, balance_sheet):
    account_map = {acct.account_ref: acct for acct in balance_sheet.accounts}
    comments_by_account = {acct.account_ref: [] for acct in balance_sheet.accounts}
    general_by_rule: dict[str, dict[str, object]] = {}

    for res in report.results:
        evidence_items = list(res.evidence_used) if res.evidence_used else []
        mapped = False

        def _general_entry() -> dict[str, object]:
            entry = general_by_rule.get(res.rule_id)
            if entry is None:
                entry = {
                    "status": _normalize_status(res.status),
                    "rule_id": res.rule_id,
                    "rule_title": res.rule_title,
                    "message": "",
                    "details": [],
                    "evidence": evidence_items,
                    "human_action": res.human_action,
                    "best_practices_reference": res.best_practices_reference,
                    "sources": res.sources,
                }
                general_by_rule[res.rule_id] = entry
            return entry

        if res.details:
            for detail in res.details:
                status = None
                if isinstance(detail.values, dict):
                    status = detail.values.get("status")
                comment = {
                    "status": _normalize_status(status or res.status),
                    "rule_id": res.rule_id,
                    "rule_title": res.rule_title,
                    "message": detail.message,
                    "values": detail.values,
                    "evidence": evidence_items,
                }
                should_map = detail.key in account_map
                if should_map and isinstance(detail.values, dict):
                    if (
                        "account_name" not in detail.values
                        and "account_ref" not in detail.values
                    ):
                        should_map = False
                if should_map:
                    mapped = True
                    comments_by_account[detail.key].append(comment)
                else:
                    entry = _general_entry()
                    entry_details = entry.get("details")
                    if isinstance(entry_details, list):
                        entry_details.append(
                            {
                                "status": _normalize_status(status or res.status),
                                "message": detail.message,
                                "values": detail.values,
                            }
                        )
        if not mapped and (res.summary or not res.details):
            entry = _general_entry()
            if res.summary:
                entry["message"] = res.summary

    return comments_by_account, list(general_by_rule.values())


def _write_html(
    report,
    balance_sheet,
    out_path: Path,
    balance_sheet_report: dict | None = None,
    comparison_reports: list[tuple[date, dict]] | None = None,
    *,
    include_rows_without_id: bool = True,
    include_summary_totals: bool = True,
) -> None:
    def _escape(value: object) -> str:
        return html_lib.escape(str(value))

    def _format_scalar(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:,.2f}"
        return str(value)

    def _format_amount(value: object) -> str:
        if value is None:
            return ""
        try:
            return f"{value:,.2f}"
        except Exception:
            return str(value)

    def _format_values(values: object) -> str:
        if values is None:
            return ""
        if isinstance(values, dict):
            rows: list[str] = []
            for key, val in values.items():
                if isinstance(val, (dict, list)):
                    rendered = json.dumps(val, default=str)
                else:
                    rendered = _format_scalar(val)
                rows.append(
                    "<tr>"
                    f"<th>{_escape(key)}</th>"
                    f"<td>{_escape(rendered)}</td>"
                    "</tr>"
                )
            return "<table class='kv'>" + "".join(rows) + "</table>"
        if isinstance(values, list):
            items = "".join(
                f"<li>{_escape(_format_scalar(item))}</li>" for item in values
            )
            return f"<ul class='kv-list'>{items}</ul>"
        return _escape(values)

    def _format_evidence(evidence_list) -> str:
        if not evidence_list:
            return ""
        parts: list[str] = []
        for ev in evidence_list:
            label = ev.evidence_type
            if ev.amount is not None:
                label = f"{label} {ev.amount}"
            if ev.as_of_date:
                label = f"{label} as of {ev.as_of_date}"
            safe_label = _escape(label)
            if ev.uri:
                uri = html_lib.escape(str(ev.uri), quote=True)
                parts.append(f"<li><a href='{uri}' target='_blank'>{safe_label}</a></li>")
            else:
                parts.append(f"<li>{safe_label}</li>")
        return "<ul class='evidence-list'>" + "".join(parts) + "</ul>"

    def _find_column_index(report: dict, col_key: str) -> int | None:
        cols = report.get("Columns", {}).get("Column")
        if not isinstance(cols, list):
            return None
        for idx, col in enumerate(cols):
            if not isinstance(col, dict):
                continue
            meta = col.get("MetaData")
            if not isinstance(meta, list):
                continue
            for m in meta:
                if not isinstance(m, dict):
                    continue
                if m.get("Name") == "ColKey" and m.get("Value") == col_key:
                    return idx
        return None

    def _parse_amount(value: object) -> object:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.replace(",", "").strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return stripped
        return value

    account_ref_by_id: dict[str, str] = {}
    for acct in balance_sheet.accounts:
        if not acct.account_ref:
            continue
        raw_id = acct.account_ref.split("::")[-1]
        if raw_id and raw_id not in account_ref_by_id:
            account_ref_by_id[raw_id] = acct.account_ref

    def _build_display_rows(report: dict | None) -> list[dict[str, object]]:
        if not isinstance(report, dict):
            return []
        account_col = _find_column_index(report, "account")
        total_col = _find_column_index(report, "total")
        account_col = 0 if account_col is None else account_col
        total_col = 1 if total_col is None else total_col
        rows = report.get("Rows")
        if not isinstance(rows, dict):
            return []

        display_rows: list[dict[str, object]] = []

        def _extract_coldata(coldata: object) -> tuple[str, str | None, object | None]:
            if not isinstance(coldata, list):
                return "", None, None
            if account_col >= len(coldata) or total_col >= len(coldata):
                return "", None, None
            acct_cell = coldata[account_col]
            total_cell = coldata[total_col]
            if not isinstance(acct_cell, dict) or not isinstance(total_cell, dict):
                return "", None, None
            name = acct_cell.get("value") if isinstance(acct_cell.get("value"), str) else ""
            account_id = acct_cell.get("id") if isinstance(acct_cell.get("id"), str) else None
            amount = _parse_amount(total_cell.get("value"))
            return name, account_id, amount

        def _row_key(name: str, account_id: str | None, row_type: str) -> str | None:
            if account_id and account_id.strip():
                return f"id::{account_id.strip()}"
            if row_type in ("data", "summary") and include_rows_without_id and name:
                return f"name::{name}"
            return None

        def _add_row(
            name: str,
            account_id: str | None,
            amount: object | None,
            indent: int,
            row_type: str,
        ) -> None:
            if not name and amount is None:
                return
            account_ref = None
            if account_id and account_id.strip():
                account_ref = account_ref_by_id.get(account_id.strip(), account_id.strip())
            elif row_type in ("data", "summary") and include_rows_without_id:
                account_ref = f"report::{name}".strip() or "report::unknown"
            display_rows.append(
                {
                    "name": name,
                    "amount": amount,
                    "account_ref": account_ref,
                    "indent": indent,
                    "row_type": row_type,
                    "row_key": _row_key(name, account_id, row_type),
                }
            )

        def _walk(container: dict, indent: int) -> None:
            row_list = container.get("Row")
            if not isinstance(row_list, list):
                return
            for row in row_list:
                if not isinstance(row, dict):
                    continue
                if row.get("type") == "Data":
                    name, account_id, amount = _extract_coldata(row.get("ColData"))
                    _add_row(name, account_id, amount, indent, "data")
                    continue

                header = row.get("Header")
                if isinstance(header, dict):
                    name, account_id, amount = _extract_coldata(header.get("ColData"))
                    _add_row(name, account_id, amount, indent, "header")

                nested = row.get("Rows")
                if isinstance(nested, dict):
                    _walk(nested, indent + 1)

                if include_summary_totals and isinstance(row.get("Summary"), dict):
                    name, account_id, amount = _extract_coldata(row["Summary"].get("ColData"))
                    if name and "total" in name.lower():
                        _add_row(name, account_id, amount, indent + 1, "summary")

        _walk(rows, 0)
        return display_rows

    def _build_amount_lookup(report: dict) -> dict[str, object]:
        lookup: dict[str, object] = {}
        account_col = _find_column_index(report, "account")
        total_col = _find_column_index(report, "total")
        account_col = 0 if account_col is None else account_col
        total_col = 1 if total_col is None else total_col
        rows = report.get("Rows")
        if not isinstance(rows, dict):
            return lookup

        def _extract_key(coldata: object, row_type: str) -> tuple[str | None, object | None]:
            if not isinstance(coldata, list):
                return None, None
            if account_col >= len(coldata) or total_col >= len(coldata):
                return None, None
            acct_cell = coldata[account_col]
            total_cell = coldata[total_col]
            if not isinstance(acct_cell, dict) or not isinstance(total_cell, dict):
                return None, None
            name = acct_cell.get("value") if isinstance(acct_cell.get("value"), str) else ""
            account_id = acct_cell.get("id") if isinstance(acct_cell.get("id"), str) else None
            key = None
            if account_id and account_id.strip():
                key = f"id::{account_id.strip()}"
            elif row_type in ("data", "summary") and include_rows_without_id and name:
                key = f"name::{name}"
            amount = _parse_amount(total_cell.get("value"))
            return key, amount

        def _walk(container: dict) -> None:
            row_list = container.get("Row")
            if not isinstance(row_list, list):
                return
            for row in row_list:
                if not isinstance(row, dict):
                    continue
                if row.get("type") == "Data":
                    key, amount = _extract_key(row.get("ColData"), "data")
                    if key is not None and amount is not None:
                        lookup.setdefault(key, amount)
                    continue

                header = row.get("Header")
                if isinstance(header, dict):
                    key, amount = _extract_key(header.get("ColData"), "header")
                    if key is not None and amount is not None:
                        lookup.setdefault(key, amount)

                nested = row.get("Rows")
                if isinstance(nested, dict):
                    _walk(nested)

                if include_summary_totals and isinstance(row.get("Summary"), dict):
                    key, amount = _extract_key(row["Summary"].get("ColData"), "summary")
                    if key and amount is not None:
                        lookup.setdefault(key, amount)

        _walk(rows)
        return lookup

    comments_by_account, general_results = _collect_review_comments(report, balance_sheet)
    status_rank = {
        "FAIL": 4,
        "NEEDS_REVIEW": 3,
        "WARN": 2,
        "PASS": 1,
        "NOT_APPLICABLE": 0,
    }

    def _worst_status(statuses: list[str]) -> str:
        if not statuses:
            return ""
        return max(statuses, key=lambda s: status_rank.get(s, 0))

    lines: list[str] = []
    lines.append("<!DOCTYPE html>")
    lines.append("<html lang='en'>")
    lines.append("<head>")
    lines.append("<meta charset='utf-8'>")
    lines.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    lines.append(f"<title>Balance Sheet Review {report.period_end}</title>")
    lines.append("<style>")
    lines.append("body{font-family:'Libre Franklin',Arial,sans-serif;margin:20px;color:#111;background:#fff;}")
    lines.append("h1,h2,h3{margin:0 0 8px 0;}")
    lines.append(".meta{color:#444;margin-bottom:16px;font-size:12px;}")
    lines.append(
        ".summary span{display:inline-block;margin-right:10px;padding:4px 8px;"
        "background:#f2f2f2;border:1px solid #ddd;border-radius:4px;font-size:12px;}"
    )
    lines.append(
        "table{width:100%;border-collapse:collapse;margin-top:12px;}"
        "th,td{border:1px solid #ccc;padding:6px;text-align:left;vertical-align:top;font-size:12px;}"
    )
    lines.append("th{background:#f7f7f7;font-weight:600;}")
    lines.append(".amount{text-align:right;white-space:nowrap;}")
    lines.append(".account-name{white-space:pre;}")
    lines.append(".comment{padding:8px 10px;border:1px solid #e5e5e5;border-radius:6px;margin-bottom:8px;background:#fafafa;}")
    lines.append(".comment:last-child{margin-bottom:0;}")
    lines.append(".comment-header{font-weight:600;margin-bottom:6px;}")
    lines.append(".comment-title{font-weight:600;}")
    lines.append(".comment-body{margin-bottom:6px;}")
    lines.append(".comment-meta{color:#333;font-size:11px;margin-top:4px;}")
    lines.append(".status{display:inline-block;font-weight:600;padding:1px 6px;border-radius:3px;}")
    lines.append(".status-badges .status{margin:0 4px 4px 0;}")
    lines.append(".status-PASS{background:#d9ead3;}")
    lines.append(".status-WARN{background:#fff2cc;}")
    lines.append(".status-FAIL{background:#f4cccc;}")
    lines.append(".status-NEEDS_REVIEW{background:#ffe599;}")
    lines.append(".status-NOT_APPLICABLE{background:#e7e7e7;}")
    lines.append(".status-col{white-space:nowrap;text-align:center;}")
    lines.append(".row-header td{background:#f7f7f7;font-weight:600;}")
    lines.append(".row-summary td{background:#fcfcfc;font-weight:600;}")
    lines.append("details{margin-top:6px;}")
    lines.append("summary{cursor:pointer;font-weight:600;color:#333;}")
    lines.append(".detail-item{margin-top:6px;padding-top:6px;border-top:1px solid #e5e5e5;}")
    lines.append(".detail-item:first-child{border-top:none;padding-top:0;margin-top:0;}")
    lines.append(".kv{width:100%;border-collapse:collapse;margin-top:4px;font-size:11px;}")
    lines.append(".kv th,.kv td{border:1px solid #e1e1e1;padding:4px;}")
    lines.append(".kv th{background:#f3f3f3;width:34%;}")
    lines.append(".kv-list{margin:4px 0 0 18px;padding:0;}")
    lines.append(".evidence-list{margin:4px 0 0 18px;padding:0;}")
    lines.append("</style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append(f"<h1>Balance Sheet</h1>")
    lines.append(f"<div class='meta'>As of {report.period_end} • Generated at {report.generated_at.isoformat()}</div>")
    lines.append("<h2>Results Summary</h2>")
    lines.append("<div class='summary'>")
    for status, count in report.totals.items():
        lines.append(f"<span>{_escape(status)}: {count}</span>")
    lines.append("</div>")
    period_reports: list[tuple[date, dict]] = []
    if comparison_reports:
        period_reports.extend(comparison_reports)
    if balance_sheet_report:
        period_reports.append((report.period_end, balance_sheet_report))
    period_labels = [p.isoformat() for p, _ in period_reports]
    period_lookups = [
        _build_amount_lookup(rep) for _, rep in period_reports if isinstance(rep, dict)
    ]

    lines.append("<table>")
    if period_labels:
        amount_headers = "".join(
            f"<th class='amount'>{_escape(label)}</th>" for label in period_labels
        )
        lines.append(
            "<thead><tr><th>Account</th>"
            f"{amount_headers}<th class='status-col'>Status</th><th>Comments</th></tr></thead>"
        )
    else:
        lines.append(
            "<thead><tr><th>Account</th><th class='amount'>Amount</th>"
            "<th class='status-col'>Status</th><th>Comments</th></tr></thead>"
        )
    lines.append("<tbody>")
    display_rows = _build_display_rows(balance_sheet_report)
    if not display_rows:
        display_rows = [
            {
                "name": acct.name,
                "amount": acct.balance,
                "account_ref": acct.account_ref,
                "indent": 0,
                "row_type": "data",
            }
            for acct in balance_sheet.accounts
        ]
    for row in display_rows:
        account_ref = row.get("account_ref")
        comments = comments_by_account.get(account_ref, []) if account_ref else []
        seen_rules: set[str] = set()
        status_badges: list[str] = []
        for comment in comments:
            rule_id = str(comment.get("rule_id") or "")
            status = comment.get("status")
            if not rule_id or rule_id in seen_rules or not status:
                continue
            seen_rules.add(rule_id)
            status_badges.append(
                f"<span class='status status-{_escape(status)}'>{_escape(status)}</span>"
            )
        comment_html_parts: list[str] = []
        for comment in comments:
            evidence_html = _format_evidence(comment.get("evidence"))
            values_html = _format_values(comment.get("values"))
            details_parts: list[str] = []
            if values_html:
                details_parts.append(
                    f"<div class='comment-meta'><strong>Values:</strong> {values_html}</div>"
                )
            if evidence_html:
                details_parts.append(
                    f"<div class='comment-meta'><strong>Evidence:</strong> {evidence_html}</div>"
                )
            details_html = ""
            if details_parts:
                details_html = (
                    "<details><summary>Details</summary>"
                    + "".join(details_parts)
                    + "</details>"
                )
            comment_html_parts.append(
                "\n".join(
                    [
                        "<div class='comment'>",
                        (
                            "<div class='comment-header'>"
                            f"<span class='comment-title'>{_escape(comment['rule_id'])}</span>"
                            f"<span>— {_escape(comment['rule_title'])}</span></div>"
                        ),
                        f"<div class='comment-body'>{_escape(comment['message'])}</div>",
                        details_html,
                        "</div>",
                    ]
                )
            )
        if comment_html_parts:
            comment_html = "\n".join(comment_html_parts)
        elif account_ref:
            comment_html = "<div class='comment-meta'>No review comments.</div>"
        else:
            comment_html = ""
        row_type = row.get("row_type") or "data"
        indent_px = int(row.get("indent") or 0) * 16
        row_class = f"row-{_escape(row_type)}"
        account_name = _escape(row.get("name") or "")
        amount_cells: list[str] = []
        if period_labels:
            row_key = row.get("row_key")
            for idx, _label in enumerate(period_labels):
                amount_value = None
                if row_key:
                    amount_value = period_lookups[idx].get(row_key)
                if amount_value is None and idx == len(period_labels) - 1:
                    amount_value = row.get("amount")
                amount_cells.append(
                    f"<td class='amount'>{_escape(_format_amount(amount_value))}</td>"
                )
        else:
            amount_cells.append(
                f"<td class='amount'>{_escape(_format_amount(row.get('amount')))}</td>"
            )
        status_html = ""
        if status_badges:
            status_html = "<div class='status-badges'>" + "".join(status_badges) + "</div>"
        lines.append(
            f"<tr class='{row_class}'>"
            f"<td class='account-name' style='padding-left:{indent_px}px'>{account_name}</td>"
            f"{''.join(amount_cells)}"
            f"<td class='status-col'>{status_html}</td>"
            f"<td>{comment_html}</td>"
            "</tr>"
        )
    lines.append("</tbody>")
    lines.append("</table>")

    if general_results:
        lines.append("<h2>Other Review Results</h2>")
        lines.append("<div>")
        for comment in general_results:
            evidence_html = _format_evidence(comment.get("evidence"))
            lines.append("<div class='comment'>")
            lines.append(
                "<div class='comment-header'>"
                f"<span class='status status-{_escape(comment['status'])}'>"
                f"{_escape(comment['status'])}</span>"
                f"<span class='comment-title'>{_escape(comment['rule_id'])}</span>"
                f"<span>— {_escape(comment['rule_title'])}</span></div>"
            )
            if comment.get("message"):
                lines.append(f"<div class='comment-body'>{_escape(comment['message'])}</div>")
            details_parts: list[str] = []
            if comment.get("human_action"):
                details_parts.append(
                    f"<div class='comment-meta'><strong>Action:</strong> "
                    f"{_escape(comment['human_action'])}</div>"
                )
            if comment.get("best_practices_reference"):
                details_parts.append(
                    f"<div class='comment-meta'><strong>Reference:</strong> "
                    f"{_escape(comment['best_practices_reference'])}</div>"
                )
            if comment.get("sources"):
                details_parts.append(
                    f"<div class='comment-meta'><strong>Sources:</strong> "
                    f"{_escape(', '.join(comment['sources']))}</div>"
                )
            detail_items: list[str] = []
            for detail in comment.get("details", []) or []:
                detail_values = _format_values(detail.get("values"))
                detail_status = detail.get("status")
                detail_header = (
                    f"<span class='status status-{_escape(detail_status)}'>"
                    f"{_escape(detail_status)}</span> "
                    if detail_status
                    else ""
                )
                values_html = (
                    f"<div class='comment-meta'><strong>Values:</strong> {detail_values}</div>"
                    if detail_values
                    else ""
                )
                detail_items.append(
                    "<div class='detail-item'>"
                    f"<div class='comment-meta'><strong>{detail_header}{_escape(detail.get('message',''))}</strong></div>"
                    f"{values_html}"
                    "</div>"
                )
            if detail_items:
                details_parts.append("<div>" + "".join(detail_items) + "</div>")
            if evidence_html:
                details_parts.append(
                    f"<div class='comment-meta'><strong>Evidence:</strong> {evidence_html}</div>"
                )
            if details_parts:
                lines.append("<details><summary>Details</summary>" + "".join(details_parts) + "</details>")
            lines.append("</div>")
        lines.append("</div>")

    lines.append("</body></html>")
    out_path.write_text("\n".join(lines))


def _normalize_account_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", name.lower()).strip()
    return " ".join(cleaned.split())


def _parse_month_year(cell: str) -> tuple[int, int] | None:
    if not cell:
        return None
    token_map = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    parts = re.split(r"\s+", cell.replace(",", " ").strip())
    year = None
    month = None
    for i, part in enumerate(parts):
        if part.isdigit() and len(part) == 4:
            year = int(part)
            if i > 0:
                month_token = parts[i - 1].lower().rstrip(".")
                month = token_map.get(month_token)
            break
    if year and month:
        return month, year
    return None


def _write_csv(
    report,
    balance_sheet,
    out_path: Path,
    template_path: Path | None = None,
) -> None:
    def _format_amount(value: object) -> str:
        try:
            return f"{value:,.2f}"
        except Exception:
            return str(value)

    def _format_values(values: object) -> str:
        if values is None:
            return ""
        if isinstance(values, (dict, list)):
            return json.dumps(values, default=str)
        return str(values)

    def _format_evidence(evidence_list) -> str:
        if not evidence_list:
            return ""
        parts: list[str] = []
        for ev in evidence_list:
            label = ev.evidence_type
            if ev.amount is not None:
                label = f"{label} {ev.amount}"
            if ev.as_of_date:
                label = f"{label} as of {ev.as_of_date}"
            if ev.uri:
                label = f"{label} ({ev.uri})"
            parts.append(label)
        return ", ".join(parts)

    def _format_comment(comment: dict[str, object]) -> str:
        lines = [f"[{comment['status']}] {comment['rule_id']} - {comment['rule_title']}"]
        if comment.get("message"):
            lines.append(str(comment["message"]))
        details = comment.get("details")
        if details:
            lines.append("Details:")
            for detail in details:
                status = detail.get("status")
                prefix = f"[{status}] " if status else ""
                lines.append(f"{prefix}{detail.get('message', '')}")
                if detail.get("values"):
                    lines.append(f"Values: {_format_values(detail.get('values'))}")
        if comment.get("values"):
            lines.append(f"Values: {_format_values(comment.get('values'))}")
        if comment.get("human_action"):
            lines.append(f"Action: {comment['human_action']}")
        if comment.get("best_practices_reference"):
            lines.append(f"Reference: {comment['best_practices_reference']}")
        if comment.get("sources"):
            lines.append(f"Sources: {', '.join(comment['sources'])}")
        evidence = _format_evidence(comment.get("evidence"))
        if evidence:
            lines.append(f"Evidence: {evidence}")
        return "\n".join(lines)

    comments_by_account, general_results = _collect_review_comments(report, balance_sheet)

    if template_path and template_path.exists():
        with template_path.open(newline="") as handle:
            template_rows = list(csv.reader(handle))
        if not template_rows:
            template_rows = []

        width = max((len(r) for r in template_rows), default=0)
        header_idx = None
        comment_col = None
        for idx, row in enumerate(template_rows):
            for col_idx, cell in enumerate(row):
                if "comment" in (cell or "").lower():
                    header_idx = idx
                    comment_col = col_idx
                    break
            if header_idx is not None:
                break

        if comment_col is None:
            comment_col = max(0, width - 1)

        period_col = None
        if header_idx is not None and template_rows:
            header_row = template_rows[header_idx]
            for col_idx, cell in enumerate(header_row):
                if col_idx >= comment_col:
                    break
                parsed = _parse_month_year(cell)
                if parsed and parsed == (report.period_end.month, report.period_end.year):
                    period_col = col_idx
                    break
            if period_col is None:
                for col_idx in range(comment_col - 1, -1, -1):
                    if col_idx < len(header_row) and header_row[col_idx].strip():
                        period_col = col_idx
                        break

        amount_by_name: dict[str, str] = {}
        comments_by_name: dict[str, list[dict[str, object]]] = {}
        for acct in balance_sheet.accounts:
            norm = _normalize_account_name(acct.name)
            if norm and norm not in amount_by_name:
                amount_by_name[norm] = _format_amount(acct.balance)
            acct_comments = comments_by_account.get(acct.account_ref, [])
            if acct_comments:
                comments_by_name.setdefault(norm, []).extend(acct_comments)

        with out_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            for idx, row in enumerate(template_rows):
                padded = row + [""] * (width - len(row))
                label = padded[0] if padded else ""
                padded = [label] + [""] * (width - 1)
                if idx == header_idx:
                    if period_col is not None:
                        padded[period_col] = report.period_end.strftime("%b. %Y")
                    padded[comment_col] = "Comments"
                else:
                    norm_label = _normalize_account_name(label)
                    if period_col is not None and norm_label in amount_by_name:
                        amount_value = amount_by_name[norm_label]
                        if amount_value:
                            padded[period_col] = amount_value
                    if norm_label in comments_by_name:
                        comment_text = "\n\n".join(
                            _format_comment(c) for c in comments_by_name[norm_label]
                        )
                        padded[comment_col] = comment_text
                writer.writerow(padded)

            writer.writerow([])
            writer.writerow(["Results Summary"] + [""] * (width - 1))
            for status, count in report.totals.items():
                row = ["", "", ""]
                row[0] = status
                row[1] = str(count)
                row += [""] * (width - len(row))
                writer.writerow(row[:width])

            if general_results:
                writer.writerow([])
                writer.writerow(["Other Review Results"] + [""] * (width - 1))
                for comment in general_results:
                    row = [""] * width
                    row[0] = f"{comment['rule_id']} - {comment['rule_title']}"
                    row[1] = str(comment["status"])
                    row[comment_col] = _format_comment(comment)
                    writer.writerow(row)
        return

    with out_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Balance Sheet", "", ""])
        writer.writerow([f"As of {report.period_end}", "", ""])
        writer.writerow([])
        writer.writerow(["Results Summary", "", ""])
        for status, count in report.totals.items():
            writer.writerow([status, count, ""])
        writer.writerow([])
        writer.writerow(["Account", "Amount", "Comments"])
        for acct in balance_sheet.accounts:
            comments = comments_by_account.get(acct.account_ref, [])
            if comments:
                comment_text = "\n\n".join(_format_comment(c) for c in comments)
            else:
                comment_text = "No review comments."
            writer.writerow([acct.name, _format_amount(acct.balance), comment_text])
        if general_results:
            writer.writerow([])
            writer.writerow(["Other Review Results", "", ""])
            for comment in general_results:
                writer.writerow(
                    [
                        f"{comment['rule_id']} - {comment['rule_title']}",
                        comment["status"],
                        _format_comment(comment),
                    ]
                )


@dataclass(frozen=True)
class FixtureReviewInputs:
    period_end: date
    balance_sheet: object
    balance_sheet_report: dict
    prior_balance_sheets: tuple[object, ...]
    profit_and_loss: object | None
    evidence: object
    reconciliations: tuple[object, ...]


def build_fixture_review_inputs(
    fixtures_dir: Path,
    *,
    pnl_summarize_by_month: bool = False,
    include_summary_totals: bool = True,
    include_rows_without_id: bool = True,
) -> FixtureReviewInputs:
    _ensure_backend_on_path()

    from adapters.qbo.intercompany import intercompany_balance_sheets_to_evidence
    from adapters.qbo.pipeline import (
        build_qbo_aging_evidence,
        build_qbo_snapshots,
        build_qbo_tax_evidence,
    )
    from adapters.qbo.balance_sheet import balance_sheet_snapshot_from_report
    from adapters.qbo.accounts import account_type_map_from_accounts_payload
    from adapters.mock_evidence.evidence_manifest import evidence_bundle_from_manifest
    from adapters.mock_evidence.reconciliation_report import (
        reconciliation_snapshot_from_report,
    )
    from adapters.working_papers.prepaid_schedule import prepaid_schedule_to_evidence
    from common.rules_engine.models import EvidenceBundle

    balance_sheet_report = _load_json(fixtures_dir / "balance_sheet.json")
    profit_and_loss_report = _load_json(fixtures_dir / "profit_and_loss.json")
    accounts_payload = _load_json(fixtures_dir / "accounts.json")
    ap_summary = _load_json(fixtures_dir / "aged_payables_summary.json")
    ap_detail = _load_json(fixtures_dir / "aged_payables_detail.json")
    ar_summary = _load_json(fixtures_dir / "aged_receivables_summary.json")
    ar_detail = _load_json(fixtures_dir / "aged_receivables_detail.json")

    snapshots = build_qbo_snapshots(
        balance_sheet_report=balance_sheet_report,
        profit_and_loss_report=profit_and_loss_report,
        accounts_payload=accounts_payload,
        include_rows_without_id=include_rows_without_id,
        include_summary_totals=include_summary_totals,
        pnl_summarize_by_month=pnl_summarize_by_month,
    )
    account_type_map = account_type_map_from_accounts_payload(accounts_payload)
    prior_balance_sheets: list[object] = []
    for _period, prior_report in _load_prior_balance_sheet_reports(
        fixtures_dir, snapshots.balance_sheet.as_of_date, count=3
    ):
        prior_balance_sheets.append(
            balance_sheet_snapshot_from_report(
                prior_report,
                account_types=account_type_map,
                include_rows_without_id=False,
                include_summary_totals=False,
            )
        )

    aging_bundle = build_qbo_aging_evidence(
        ap_summary_report=ap_summary,
        ap_detail_report=ap_detail,
        ar_summary_report=ar_summary,
        ar_detail_report=ar_detail,
    )

    tax_agencies = _load_json(fixtures_dir / "tax_agencies.json")
    tax_returns = _load_json(fixtures_dir / "tax_returns.json")
    tax_payments = _load_json(fixtures_dir / "tax_payments.json")
    tax_bundle = build_qbo_tax_evidence(
        tax_agencies_payload=tax_agencies,
        tax_returns_payload=tax_returns,
        tax_payments_payload=tax_payments,
    )

    items = []
    items += aging_bundle.items
    items += tax_bundle.items

    intercompany_payload = _load_optional_json(
        fixtures_dir / "intercompany_balance_sheets.json"
    )
    if intercompany_payload is not None:
        items.append(
            intercompany_balance_sheets_to_evidence(
                intercompany_payload, as_of_date=snapshots.balance_sheet.as_of_date
            )
        )

    manifest_payload = _load_optional_json(fixtures_dir / "evidence_manifest.json")
    if manifest_payload is not None:
        items += evidence_bundle_from_manifest(manifest_payload).items

    prepaid_csv = fixtures_dir / "Blackbird Fabrics _ Prepaid Schedule - Prepaid.csv"
    if prepaid_csv.exists():
        items.append(
            prepaid_schedule_to_evidence(
                prepaid_csv, period_end=snapshots.balance_sheet.as_of_date
            )
        )

    reconciliations = []
    for path in fixtures_dir.glob("reconciliation_report_*.json"):
        report = _load_json(path)
        reconciliations.append(reconciliation_snapshot_from_report(report, source="fixture"))

    return FixtureReviewInputs(
        period_end=snapshots.balance_sheet.as_of_date,
        balance_sheet=snapshots.balance_sheet,
        balance_sheet_report=balance_sheet_report,
        prior_balance_sheets=tuple(prior_balance_sheets),
        profit_and_loss=snapshots.profit_and_loss,
        evidence=EvidenceBundle(items=items),
        reconciliations=tuple(reconciliations),
    )


def build_evidence_bundle_from_fixtures(
    fixtures_dir: Path,
    *,
    pnl_summarize_by_month: bool = False,
    include_summary_totals: bool = True,
    include_rows_without_id: bool = True,
):
    return build_fixture_review_inputs(
        fixtures_dir,
        pnl_summarize_by_month=pnl_summarize_by_month,
        include_summary_totals=include_summary_totals,
        include_rows_without_id=include_rows_without_id,
    ).evidence


def run_balance_review_from_inputs(inputs: FixtureReviewInputs):
    _ensure_backend_on_path()
    from common.rules_engine.config import ClientRulesConfig
    from common.rules_engine.context import RuleContext
    from common.rules_engine.runner import RulesRunner

    ctx = RuleContext(
        period_end=inputs.period_end,
        balance_sheet=inputs.balance_sheet,
        prior_balance_sheets=inputs.prior_balance_sheets,
        profit_and_loss=inputs.profit_and_loss,
        evidence=inputs.evidence,
        reconciliations=inputs.reconciliations,
        client_config=ClientRulesConfig(rules={}),
    )
    return RulesRunner().run(ctx)


def run_balance_review_from_fixtures(
    fixtures_dir: Path,
    *,
    pnl_summarize_by_month: bool = False,
    include_summary_totals: bool = True,
    include_rows_without_id: bool = True,
):
    inputs = build_fixture_review_inputs(
        fixtures_dir,
        pnl_summarize_by_month=pnl_summarize_by_month,
        include_summary_totals=include_summary_totals,
        include_rows_without_id=include_rows_without_id,
    )
    return run_balance_review_from_inputs(inputs)


def run_balance_review_from_live(
    *,
    client_id: str,
    period_end: date,
):
    _ensure_backend_on_path()
    from pipelines.data_source import get_data_source

    source = get_data_source("live")
    inputs = source.build_review_inputs(client_id=client_id, period_end=period_end)
    return run_balance_review_from_inputs(inputs)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run MER balance review against a fixtures directory and write JSON/MD/HTML outputs."
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Client id for live data source (matches config/clients.json).",
    )
    parser.add_argument(
        "--period-end",
        default=None,
        help="Period end date (YYYY-MM-DD) for live data source.",
    )
    parser.add_argument(
        "--fixtures-dir",
        required=False,
        help="Path to a fixtures directory (e.g. src/backend/tests/rules_engine/fixtures/blackbird_fabrics/2025-12-31).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for review files (defaults to fixtures dir).",
    )
    parser.add_argument(
        "--pnl-summarize-by-month",
        action="store_true",
        help="Use the month column matching the report EndPeriod in Profit & Loss.",
    )
    parser.add_argument(
        "--exclude-summary-totals",
        action="store_false",
        dest="include_summary_totals",
        help="Exclude Balance Sheet summary total rows (Total ...).",
    )
    parser.add_argument(
        "--exclude-rows-without-id",
        action="store_false",
        dest="include_rows_without_id",
        help="Exclude Balance Sheet rows that have no account id.",
    )
    args = parser.parse_args()

    data_source = os.getenv("DATA_SOURCE", "fixtures").strip().lower()

    fixtures_dir = Path(args.fixtures_dir).resolve() if args.fixtures_dir else None
    output_dir = Path(args.output_dir).resolve() if args.output_dir else fixtures_dir
    if output_dir is None:
        output_dir = Path(".").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = None
    if data_source == "live":
        if not args.client_id or not args.period_end:
            raise SystemExit("Live mode requires --client-id and --period-end.")
        period_end = date.fromisoformat(args.period_end)
        report = run_balance_review_from_live(
            client_id=args.client_id,
            period_end=period_end,
        )
    else:
        if fixtures_dir is None:
            raise SystemExit("Fixtures mode requires --fixtures-dir.")
        inputs = build_fixture_review_inputs(
            fixtures_dir,
            pnl_summarize_by_month=args.pnl_summarize_by_month,
            include_summary_totals=args.include_summary_totals,
            include_rows_without_id=args.include_rows_without_id,
        )
        report = run_balance_review_from_inputs(inputs)

    base_name = f"balance_review_{report.period_end.isoformat()}"
    out_json = output_dir / f"{base_name}.json"
    out_md = output_dir / f"{base_name}.md"
    out_html = output_dir / f"{base_name}.html"
    out_csv = output_dir / f"{base_name}.csv"
    out_findings = output_dir / f"{base_name}_findings.json"

    out_json.write_text(json.dumps(report.model_dump(mode="json"), indent=2))
    _write_markdown(report, out_md)
    wrote_html = False
    wrote_csv = False
    if inputs is not None:
        comparison_reports = _load_prior_balance_sheet_reports(
            fixtures_dir, inputs.period_end, count=3
        )
        _write_html(
            report,
            inputs.balance_sheet,
            out_html,
            inputs.balance_sheet_report,
            comparison_reports,
            include_rows_without_id=args.include_rows_without_id,
            include_summary_totals=args.include_summary_totals,
        )
        wrote_html = True
        template_csv = None
        for candidate in fixtures_dir.glob("*.csv"):
            if "balance sheet" in candidate.name.lower():
                template_csv = candidate
                break
        _write_csv(report, inputs.balance_sheet, out_csv, template_csv)
        wrote_csv = True
    out_findings.write_text(
        json.dumps([r.model_dump(mode="json") for r in report.results], indent=2)
    )

    print(f"Wrote {out_json}")
    print(f"Wrote {out_findings}")
    print(f"Wrote {out_md}")
    if wrote_html:
        print(f"Wrote {out_html}")
    if wrote_csv:
        print(f"Wrote {out_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
