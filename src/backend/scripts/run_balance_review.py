from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_backend_on_path() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


def _load_json(path: Path):
    with path.open() as handle:
        return json.load(handle)


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


def _write_html(report, out_path: Path) -> None:
    html: list[str] = []
    html.append("<!DOCTYPE html>")
    html.append("<html lang='en'>")
    html.append("<head>")
    html.append("<meta charset='utf-8'>")
    html.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    html.append(f"<title>Balance Review {report.period_end}</title>")
    html.append("<style>")
    html.append("body{font-family:Georgia,serif;margin:24px;color:#111;background:#f6f3ee;}")
    html.append("h1,h2,h3{margin:0 0 8px 0;} .meta{color:#444;margin-bottom:16px;}")
    html.append(
        ".totals span{display:inline-block;margin-right:12px;padding:4px 8px;"
        "background:#fff;border:1px solid #ddd;border-radius:4px;}"
    )
    html.append(
        ".card{background:#fff;border:1px solid #ddd;border-radius:8px;"
        "padding:12px;margin:12px 0;}"
    )
    html.append(".status{font-weight:bold;padding:2px 6px;border-radius:4px;background:#eee;}")
    html.append(
        "table{width:100%;border-collapse:collapse;margin-top:8px;}"
        "th,td{border:1px solid #ddd;padding:6px;text-align:left;vertical-align:top;font-size:14px;}"
    )
    html.append(".details{font-size:14px;color:#222;}")
    html.append("</style>")
    html.append("</head>")
    html.append("<body>")
    html.append(f"<h1>Balance Review {report.period_end}</h1>")
    html.append(f"<div class='meta'>Generated at: {report.generated_at.isoformat()}</div>")
    html.append("<h2>Totals</h2>")
    html.append("<div class='totals'>")
    for status, count in report.totals.items():
        html.append(f"<span>{status}: {count}</span>")
    html.append("</div>")
    html.append("<h2>Results</h2>")
    for res in report.results:
        html.append("<div class='card'>")
        html.append(f"<h3>{res.rule_id} — <span class='status'>{res.status}</span></h3>")
        html.append(f"<div>{res.rule_title}</div>")
        if res.summary:
            html.append(f"<div class='details'><strong>Summary:</strong> {res.summary}</div>")
        if res.best_practices_reference:
            html.append(
                f"<div class='details'><strong>Reference:</strong> {res.best_practices_reference}</div>"
            )
        if res.sources:
            html.append(f"<div class='details'><strong>Sources:</strong> {', '.join(res.sources)}</div>")
        if res.human_action:
            html.append(f"<div class='details'><strong>Action:</strong> {res.human_action}</div>")
        if res.details:
            html.append("<table><thead><tr><th>Key</th><th>Message</th><th>Values</th></tr></thead><tbody>")
            for detail in res.details:
                html.append(
                    f"<tr><td>{detail.key}</td><td>{detail.message}</td><td>{detail.values}</td></tr>"
                )
            html.append("</tbody></table>")
        if res.evidence_used:
            html.append(
                "<table><thead><tr><th>Evidence Type</th><th>Amount</th><th>As Of</th>"
                "<th>Source</th></tr></thead><tbody>"
            )
            for ev in res.evidence_used:
                html.append(
                    f"<tr><td>{ev.evidence_type}</td><td>{ev.amount}</td>"
                    f"<td>{ev.as_of_date}</td><td>{ev.source}</td></tr>"
                )
            html.append("</tbody></table>")
        html.append("</div>")
    html.append("</body></html>")
    out_path.write_text("\n".join(html))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run MER balance review against a fixtures directory and write JSON/MD/HTML outputs."
    )
    parser.add_argument(
        "--fixtures-dir",
        required=True,
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
        "--include-summary-totals",
        action="store_true",
        help="Include Balance Sheet summary total rows (Total ...).",
    )
    args = parser.parse_args()

    _ensure_backend_on_path()

    from adapters.qbo.pipeline import (
        build_qbo_aging_evidence,
        build_qbo_snapshots,
        build_qbo_tax_evidence,
    )
    from adapters.working_papers.prepaid_schedule import prepaid_schedule_to_evidence
    from common.rules_engine.config import ClientRulesConfig
    from common.rules_engine.context import RuleContext
    from common.rules_engine.models import EvidenceBundle
    from common.rules_engine.runner import RulesRunner

    fixtures_dir = Path(args.fixtures_dir).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else fixtures_dir
    output_dir.mkdir(parents=True, exist_ok=True)

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
        include_rows_without_id=True,
        include_summary_totals=args.include_summary_totals,
        pnl_summarize_by_month=args.pnl_summarize_by_month,
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

    prepaid_csv = fixtures_dir / "Blackbird Fabrics _ Prepaid Schedule - Prepaid.csv"
    if prepaid_csv.exists():
        items.append(
            prepaid_schedule_to_evidence(prepaid_csv, period_end=snapshots.balance_sheet.as_of_date)
        )

    ctx = RuleContext(
        period_end=snapshots.balance_sheet.as_of_date,
        balance_sheet=snapshots.balance_sheet,
        profit_and_loss=snapshots.profit_and_loss,
        evidence=EvidenceBundle(items=items),
        reconciliations=(),
        client_config=ClientRulesConfig(rules={}),
    )
    report = RulesRunner().run(ctx)

    base_name = f"balance_review_{ctx.period_end.isoformat()}"
    out_json = output_dir / f"{base_name}.json"
    out_md = output_dir / f"{base_name}.md"
    out_html = output_dir / f"{base_name}.html"

    out_json.write_text(json.dumps(report.model_dump(mode=\"json\"), indent=2))
    _write_markdown(report, out_md)
    _write_html(report, out_html)

    print(f\"Wrote {out_json}\")\n+    print(f\"Wrote {out_md}\")\n+    print(f\"Wrote {out_html}\")\n+\n+    return 0\n+\n+\n+if __name__ == \"__main__\":\n+    raise SystemExit(main())\n*** End Patch"}```markdown to=functions.apply_patch  彩神争霸充值
