from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


def _ensure_backend_on_path() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


_ensure_backend_on_path()

from api.qbo_data import TransactionsByAccountRequest, qbo_get_transactions_by_account


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "account"


def _report_columns(payload: dict) -> list[str]:
    report = payload.get("report")
    if not isinstance(report, dict):
        return []
    cols = report.get("Columns")
    if not isinstance(cols, dict):
        return []
    col_list = cols.get("Column")
    if not isinstance(col_list, list):
        return []
    out: list[str] = []
    for col in col_list:
        if not isinstance(col, dict):
            continue
        title = str(col.get("ColTitle") or "").strip()
        if title:
            out.append(title)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch QBO TransactionListByAccount payloads and save raw JSON fixture files."
    )
    parser.add_argument(
        "--client-id",
        required=True,
        help="Client id for live data source (matches config/clients.json).",
    )
    parser.add_argument("--period-end", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--accounts",
        nargs="+",
        required=True,
        help="Account specs as account_id:label (example: 67:paypal_cad_account)",
    )
    parser.add_argument(
        "--out-dir",
        default="tests/rules_engine/fixtures/example_client/2025-12-31",
        help="Output fixtures directory.",
    )
    parser.add_argument("--start-date", default=None, help="Optional explicit start date YYYY-MM-DD")
    args = parser.parse_args()

    period_end = date.fromisoformat(args.period_end)
    start_date = date.fromisoformat(args.start_date) if args.start_date else date(period_end.year, period_end.month, 1)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in args.accounts:
        if ":" not in spec:
            raise ValueError(f"Invalid account spec '{spec}'. Expected account_id:label.")
        account_id, label = spec.split(":", 1)
        account_id = account_id.strip()
        label = _slug(label)
        request = TransactionsByAccountRequest(
            client_id=args.client_id,
            account_id=account_id,
            start_date=start_date,
            end_date=period_end,
            include_splits=True,
        )
        payload = qbo_get_transactions_by_account(request)
        out_path = out_dir / f"transaction_list_by_account_{label}_{period_end:%Y-%m}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        report_name = str(payload.get("report_name") or "").strip()
        columns = _report_columns(payload)
        print(f"Wrote {out_path} (report_name={report_name or 'unknown'})")
        if report_name and report_name != "TransactionListByAccount":
            print(
                "WARNING: QBO returned fallback report. This may include mixed accounts; "
                "verify account filtering before using as per-account source of truth."
            )
        lowered_columns = {c.lower() for c in columns}
        has_clear_status = any(("clear" in c or "recon" in c or "status" in c) for c in lowered_columns)
        if not has_clear_status:
            print(
                "WARNING: No clear/reconcile status column detected. "
                "Rule S1/S2 logic will likely be NEEDS_REVIEW without status evidence."
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
