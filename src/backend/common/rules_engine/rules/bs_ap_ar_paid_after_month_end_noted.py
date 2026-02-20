from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import ApArPaidAfterMonthEndNotedRuleConfig
from ..context import RuleContext
from ..models import RuleResult, RuleResultDetail, RuleStatus, StatusOrdering, severity_for_status
from ..registry import register_rule
from ..rule import Rule


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return date.fromisoformat(s)
        except Exception:
            return None
    return None


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if not s:
            return None
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


def _items_from_meta(meta: dict[str, Any]) -> list[dict[str, Any]] | None:
    items = meta.get("items")
    if items is None:
        return None
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return None


def _item_id(item: dict[str, Any]) -> str:
    for key in ("id", "txn_id", "transaction_id", "doc_number", "document_number"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _item_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("vendor") or item.get("customer") or "").strip()


def _item_amount(item: dict[str, Any]) -> Decimal | None:
    return _parse_decimal(item.get("open_balance") if "open_balance" in item else item.get("amount"))


def _item_txn_date(item: dict[str, Any]) -> date | None:
    return _parse_date(item.get("txn_date") or item.get("date") or item.get("transaction_date"))


def _item_match_key(item: dict[str, Any]) -> str | None:
    item_id = _item_id(item)
    if item_id:
        return f"id:{item_id.lower()}"

    name = _item_name(item).lower()
    if not name:
        return None

    amount = _item_amount(item)
    txn_date = _item_txn_date(item)

    if amount is not None and txn_date is not None:
        return f"name_amount_date:{name}|{amount}|{txn_date.isoformat()}"
    if amount is not None:
        return f"name_amount:{name}|{amount}"
    return f"name:{name}"


def _settled_note(
    *,
    stream_label: str,
    period_end: date,
    comparison_as_of_date: date,
) -> str:
    return (
        f"Open in {stream_label} aging as of {period_end.isoformat()} and not present as of "
        f"{comparison_as_of_date.isoformat()} (settled after month-end). Add payment/receipt date and "
        "method in MER comments."
    )


@register_rule
class BS_AP_AR_PAID_AFTER_MONTH_END_NOTED(Rule):
    rule_id = "BS-AP-AR-PAID-AFTER-MONTH-END-NOTED"
    rule_title = "Items paid after month-end are annotated in MER"
    best_practices_reference = "Accounts Payable/Receivable → Year End Adjustments"
    sources = ["QBO (Aged Payables/Receivables Detail)"]
    config_model = ApArPaidAfterMonthEndNotedRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, ApArPaidAfterMonthEndNotedRuleConfig)
        missing_status = RuleStatus(cfg.missing_data_policy.value)
        if not cfg.enabled:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary="Rule disabled by client configuration.",
            )

        if cfg.comparison_as_of_date is not None and cfg.comparison_as_of_date <= ctx.period_end:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary=(
                    "Invalid configuration: comparison_as_of_date must be after period end for paid-after-month-end "
                    "checks."
                ),
                human_action="Set comparison_as_of_date to the review date after period end (e.g., 2026-01-18).",
            )

        ap_result = self._evaluate_stream(
            ctx=ctx,
            stream_label="AP",
            stream_key="ap",
            evidence_type=cfg.ap_detail_rows_evidence_type,
            cfg=cfg,
            missing_status=missing_status,
        )
        ar_result = self._evaluate_stream(
            ctx=ctx,
            stream_label="AR",
            stream_key="ar",
            evidence_type=cfg.ar_detail_rows_evidence_type,
            cfg=cfg,
            missing_status=missing_status,
        )

        if not ap_result["has_period_end"] and not ar_result["has_period_end"]:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No AP/AR period-end aging detail evidence for {ctx.period_end.isoformat()}; not applicable.",
            )

        statuses = [ap_result["status"], ar_result["status"]]
        overall = StatusOrdering.default().worst(statuses)
        total_settled = int(ap_result["settled_count"]) + int(ar_result["settled_count"])
        has_missing_data = bool(ap_result["missing_data"] or ar_result["missing_data"])
        if has_missing_data:
            overall = missing_status

        if has_missing_data and total_settled > 0:
            summary = (
                f"Found {total_settled} settled AP/AR item(s), but missing follow-up evidence prevented complete "
                "paid-after-month-end annotation checks."
            )
        elif has_missing_data:
            summary = (
                "Missing AP/AR follow-up aging detail evidence after period end; cannot confirm paid-after-month-end "
                "items."
            )
        elif total_settled > 0:
            summary = (
                f"{total_settled} AP/AR item(s) appear settled after {ctx.period_end.isoformat()}; add MER comments "
                "with payment/receipt date and method."
            )
        else:
            summary = "No AP/AR period-end items were identified as settled in follow-up aging detail reports."

        evidence_used: list[Any] = []
        for item in ap_result["evidence_used"] + ar_result["evidence_used"]:
            if all(existing is not item for existing in evidence_used):
                evidence_used.append(item)

        human_action = None
        if has_missing_data:
            human_action = (
                "Provide AP/AR aging detail rows for both period end and review date so paid-after-month-end "
                "items can be annotated."
            )
        elif total_settled > 0:
            human_action = "Annotate each settled AP/AR item in MER with payment/receipt date and method."

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=overall,
            severity=severity_for_status(overall),
            summary=summary,
            details=[ap_result["detail"], ar_result["detail"]],
            evidence_used=evidence_used,
            human_action=human_action,
        )

    def _evaluate_stream(
        self,
        *,
        ctx: RuleContext,
        stream_label: str,
        stream_key: str,
        evidence_type: str,
        cfg: ApArPaidAfterMonthEndNotedRuleConfig,
        missing_status: RuleStatus,
    ) -> dict[str, Any]:
        detail_key = f"{stream_key}_paid_after_month_end"
        items = [item for item in ctx.evidence.items if item.evidence_type == evidence_type]

        if not items:
            return {
                "has_period_end": False,
                "missing_data": False,
                "settled_count": 0,
                "status": RuleStatus.NOT_APPLICABLE,
                "evidence_used": [],
                "detail": RuleResultDetail(
                    key=detail_key,
                    message=f"{stream_label} items settled after month-end.",
                    values={
                        "stream": stream_label,
                        "period_end": ctx.period_end.isoformat(),
                        "status": RuleStatus.NOT_APPLICABLE.value,
                        "evaluated": False,
                        "reason": "missing_period_end_evidence",
                    },
                ),
            }

        if cfg.require_period_end_evidence_date_match:
            period_item = next((item for item in items if item.as_of_date == ctx.period_end), None)
            if period_item is None:
                return {
                    "has_period_end": False,
                    "missing_data": True,
                    "settled_count": 0,
                    "status": missing_status,
                    "evidence_used": [],
                    "detail": RuleResultDetail(
                        key=detail_key,
                        message=f"{stream_label} items settled after month-end.",
                        values={
                            "stream": stream_label,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                            "evaluated": False,
                            "reason": "period_end_evidence_date_mismatch",
                            "required_as_of_date": ctx.period_end.isoformat(),
                            "available_as_of_dates": sorted(
                                {
                                    item.as_of_date.isoformat()
                                    for item in items
                                    if item.as_of_date is not None
                                }
                            ),
                        },
                    ),
                }
        else:
            period_candidates = [item for item in items if item.as_of_date and item.as_of_date <= ctx.period_end]
            period_item = max(period_candidates, key=lambda item: item.as_of_date or date.min) if period_candidates else None

        if period_item is None:
            return {
                "has_period_end": False,
                "missing_data": True,
                "settled_count": 0,
                "status": missing_status,
                "evidence_used": [],
                "detail": RuleResultDetail(
                    key=detail_key,
                    message=f"{stream_label} items settled after month-end.",
                    values={
                        "stream": stream_label,
                        "period_end": ctx.period_end.isoformat(),
                        "status": missing_status.value,
                        "evaluated": False,
                        "reason": "missing_period_end_evidence",
                    },
                ),
            }

        follow_up_item = self._select_follow_up_item(
            items=items,
            period_end=ctx.period_end,
            comparison_as_of_date=cfg.comparison_as_of_date,
        )
        if follow_up_item is None:
            return {
                "has_period_end": True,
                "missing_data": True,
                "settled_count": 0,
                "status": missing_status,
                "evidence_used": [period_item],
                "detail": RuleResultDetail(
                    key=detail_key,
                    message=f"{stream_label} items settled after month-end.",
                    values={
                        "stream": stream_label,
                        "period_end": ctx.period_end.isoformat(),
                        "period_end_as_of_date": period_item.as_of_date.isoformat()
                        if period_item.as_of_date is not None
                        else None,
                        "expected_comparison_as_of_date": cfg.comparison_as_of_date.isoformat()
                        if cfg.comparison_as_of_date is not None
                        else None,
                        "status": missing_status.value,
                        "evaluated": False,
                        "reason": "missing_follow_up_evidence",
                    },
                ),
            }

        period_rows = _items_from_meta(period_item.meta or {})
        follow_rows = _items_from_meta(follow_up_item.meta or {})
        if period_rows is None or follow_rows is None:
            return {
                "has_period_end": True,
                "missing_data": True,
                "settled_count": 0,
                "status": missing_status,
                "evidence_used": [period_item, follow_up_item],
                "detail": RuleResultDetail(
                    key=detail_key,
                    message=f"{stream_label} items settled after month-end.",
                    values={
                        "stream": stream_label,
                        "period_end": ctx.period_end.isoformat(),
                        "period_end_as_of_date": period_item.as_of_date.isoformat()
                        if period_item.as_of_date is not None
                        else None,
                        "comparison_as_of_date": follow_up_item.as_of_date.isoformat()
                        if follow_up_item.as_of_date is not None
                        else None,
                        "status": missing_status.value,
                        "evaluated": False,
                        "reason": "missing_item_level_metadata",
                    },
                ),
            }

        follow_up_keys = Counter(
            key for key in (_item_match_key(item) for item in follow_rows) if key is not None
        )

        settled_items: list[dict[str, Any]] = []
        unmatched_period_rows = 0
        comparison_as_of_date = follow_up_item.as_of_date or cfg.comparison_as_of_date or ctx.period_end
        for period_row in period_rows:
            key = _item_match_key(period_row)
            if key is None:
                unmatched_period_rows += 1
                continue
            if follow_up_keys.get(key, 0) > 0:
                follow_up_keys[key] -= 1
                continue

            amount = _item_amount(period_row)
            txn_date = _item_txn_date(period_row)
            settled_items.append(
                {
                    "item_id": _item_id(period_row) or None,
                    "name": _item_name(period_row),
                    "open_balance_at_period_end": str(amount) if amount is not None else None,
                    "txn_date": txn_date.isoformat() if txn_date is not None else None,
                    "payment_date": period_row.get("payment_date"),
                    "payment_method": period_row.get("payment_method") or period_row.get("method"),
                    "note": _settled_note(
                        stream_label=stream_label,
                        period_end=ctx.period_end,
                        comparison_as_of_date=comparison_as_of_date,
                    ),
                }
            )

        stream_status = cfg.settled_item_status if settled_items else RuleStatus.PASS
        settled_sample = settled_items[: int(cfg.max_noted_items_in_detail or 25)]

        return {
            "has_period_end": True,
            "missing_data": False,
            "settled_count": len(settled_items),
            "status": stream_status,
            "evidence_used": [period_item, follow_up_item],
            "detail": RuleResultDetail(
                key=detail_key,
                message=f"{stream_label} period-end items compared to follow-up aging detail.",
                values={
                    "stream": stream_label,
                    "period_end": ctx.period_end.isoformat(),
                    "period_end_as_of_date": period_item.as_of_date.isoformat()
                    if period_item.as_of_date is not None
                    else None,
                    "comparison_as_of_date": follow_up_item.as_of_date.isoformat()
                    if follow_up_item.as_of_date is not None
                    else None,
                    "period_end_item_count": len(period_rows),
                    "comparison_item_count": len(follow_rows),
                    "period_end_items_missing_match_key_count": unmatched_period_rows,
                    "settled_count": len(settled_items),
                    "settled_items": settled_sample,
                    "settled_items_truncated_count": max(0, len(settled_items) - len(settled_sample)),
                    "status": stream_status.value,
                },
            ),
        }

    def _select_follow_up_item(
        self,
        *,
        items: list[Any],
        period_end: date,
        comparison_as_of_date: date | None,
    ) -> Any | None:
        if comparison_as_of_date is not None:
            return next((item for item in items if item.as_of_date == comparison_as_of_date), None)

        candidates = [item for item in items if item.as_of_date is not None and item.as_of_date > period_end]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.as_of_date or date.min)
