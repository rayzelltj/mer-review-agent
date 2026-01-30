from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import ApArItemsOlderThan60DaysRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
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
        return [i for i in items if isinstance(i, dict)]
    return None


@register_rule
class BS_AP_AR_ITEMS_OLDER_THAN_60_DAYS(Rule):
    rule_id = "BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS"
    rule_title = "AP/AR items older than 60 days flagged"
    best_practices_reference = "Accounts Payable/Receivable"
    sources = ["QBO (AP/AR Aging Summary + Detail)"]
    config_model = ApArItemsOlderThan60DaysRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, ApArItemsOlderThan60DaysRuleConfig)
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

        threshold_days = int(cfg.age_threshold_days or 60)
        cutoff = ctx.period_end - timedelta(days=threshold_days)

        ap_summary = ctx.evidence.first(cfg.ap_summary_evidence_type)
        ap_detail = ctx.evidence.first(cfg.ap_detail_evidence_type)
        ar_summary = ctx.evidence.first(cfg.ar_summary_evidence_type)
        ar_detail = ctx.evidence.first(cfg.ar_detail_evidence_type)

        missing_status = RuleStatus(cfg.missing_data_policy.value)

        evidence_items = [
            ("AP summary", ap_summary),
            ("AP detail", ap_detail),
            ("AR summary", ar_summary),
            ("AR detail", ar_detail),
        ]
        for label, item in evidence_items:
            if item is None or item.amount is None:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=missing_status,
                    severity=severity_for_status(missing_status),
                    summary=f"Missing {label} aging total for {ctx.period_end.isoformat()}; cannot verify.",
                    evidence_used=[item] if item else [],
                    human_action="Provide AP/AR aging summary and detail totals as of period end.",
                )
            if cfg.require_evidence_as_of_date_match_period_end:
                if item.as_of_date is None or item.as_of_date != ctx.period_end:
                    return RuleResult(
                        rule_id=self.rule_id,
                        rule_title=self.rule_title,
                        best_practices_reference=self.best_practices_reference,
                        sources=self.sources,
                        status=missing_status,
                        severity=severity_for_status(missing_status),
                        summary=(
                            f"{label} aging report as-of date is missing or does not match period end; "
                            "cannot verify."
                        ),
                        evidence_used=[item],
                        human_action="Provide AP/AR aging reports as of the period end date.",
                    )

        ap_detail_items = _items_from_meta(ap_detail.meta or {})
        ap_summary_items = _items_from_meta(ap_summary.meta or {})
        ar_detail_items = _items_from_meta(ar_detail.meta or {})
        ar_summary_items = _items_from_meta(ar_summary.meta or {})

        if ap_detail_items is None or ap_summary_items is None or ar_detail_items is None or ar_summary_items is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Missing item-level metadata for AP/AR aging reports; cannot verify.",
                evidence_used=[ap_summary, ap_detail, ar_summary, ar_detail],
                human_action="Provide item-level metadata for AP/AR aging reports (items older than threshold).",
            )

        ap_detail_over, ap_invalid = self._filter_over_threshold(ap_detail_items, cutoff, threshold_days)
        ar_detail_over, ar_invalid = self._filter_over_threshold(ar_detail_items, cutoff, threshold_days)

        if ap_invalid or ar_invalid:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Some AP/AR detail items are missing dates or amounts; cannot verify.",
                evidence_used=[ap_detail, ar_detail],
                human_action="Ensure AP/AR detail items include valid dates and amounts.",
            )

        ap_summary_map = self._summary_map(ap_summary_items)
        ar_summary_map = self._summary_map(ar_summary_items)
        ap_detail_map = self._summary_map(ap_detail_over)
        ar_detail_map = self._summary_map(ar_detail_over)

        ap_discrepancies = self._diff_maps(ap_detail_map, ap_summary_map)
        ar_discrepancies = self._diff_maps(ar_detail_map, ar_summary_map)

        ap_over_total = quantize_amount(_parse_decimal(ap_detail.amount) or Decimal("0"), cfg.amount_quantize)
        ar_over_total = quantize_amount(_parse_decimal(ar_detail.amount) or Decimal("0"), cfg.amount_quantize)
        ap_summary_total = quantize_amount(_parse_decimal(ap_summary.amount) or Decimal("0"), cfg.amount_quantize)
        ar_summary_total = quantize_amount(_parse_decimal(ar_summary.amount) or Decimal("0"), cfg.amount_quantize)

        ap_calc_total = sum(ap_detail_map.values(), Decimal("0"))
        ar_calc_total = sum(ar_detail_map.values(), Decimal("0"))
        if ap_calc_total != ap_over_total or ap_calc_total != ap_summary_total:
            ap_discrepancies.append(
                {
                    "name": "__TOTAL__",
                    "detail_total": str(ap_calc_total),
                    "summary_total": str(ap_summary_total),
                    "difference": str(abs(ap_calc_total - ap_summary_total)),
                }
            )
        if ar_calc_total != ar_over_total or ar_calc_total != ar_summary_total:
            ar_discrepancies.append(
                {
                    "name": "__TOTAL__",
                    "detail_total": str(ar_calc_total),
                    "summary_total": str(ar_summary_total),
                    "difference": str(abs(ar_calc_total - ar_summary_total)),
                }
            )

        ap_has_old = len(ap_detail_over) > 0
        ar_has_old = len(ar_detail_over) > 0
        has_discrepancy = bool(ap_discrepancies or ar_discrepancies)

        if ap_has_old or ar_has_old or has_discrepancy:
            status = RuleStatus.NEEDS_REVIEW
            summary = "AP/AR items older than threshold detected or report discrepancies found."
            human_action = (
                "Review AP/AR items older than the threshold and reconcile summary vs detail report discrepancies."
            )
        else:
            status = RuleStatus.PASS
            summary = "No AP/AR items older than the threshold and reports reconcile."
            human_action = None

        details = [
            RuleResultDetail(
                key="ap_over_60",
                message="AP items older than threshold.",
                values={
                    "period_end": ctx.period_end.isoformat(),
                    "threshold_days": threshold_days,
                    "cutoff_date": cutoff.isoformat(),
                    "over_threshold_count": len(ap_detail_over),
                    "over_threshold_items": ap_detail_over[:25],
                    "invalid_items_count": ap_invalid,
                    "detail_total_over_threshold": str(ap_over_total),
                    "summary_total_over_threshold": str(ap_summary_total),
                    "discrepancies": ap_discrepancies,
                    "status": status.value,
                },
            ),
            RuleResultDetail(
                key="ar_over_60",
                message="AR items older than threshold.",
                values={
                    "period_end": ctx.period_end.isoformat(),
                    "threshold_days": threshold_days,
                    "cutoff_date": cutoff.isoformat(),
                    "over_threshold_count": len(ar_detail_over),
                    "over_threshold_items": ar_detail_over[:25],
                    "invalid_items_count": ar_invalid,
                    "detail_total_over_threshold": str(ar_over_total),
                    "summary_total_over_threshold": str(ar_summary_total),
                    "discrepancies": ar_discrepancies,
                    "status": status.value,
                },
            ),
        ]

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=status,
            severity=severity_for_status(status),
            summary=summary,
            details=details,
            evidence_used=[ap_summary, ap_detail, ar_summary, ar_detail],
            human_action=human_action,
        )

    def _filter_over_threshold(
        self, items: list[dict[str, Any]], cutoff: date, threshold_days: int
    ) -> tuple[list[dict[str, Any]], int]:
        out: list[dict[str, Any]] = []
        invalid_count = 0
        for item in items:
            txn_date = _parse_date(item.get("txn_date") or item.get("date") or item.get("transaction_date"))
            amt = _parse_decimal(item.get("amount"))
            age_days = item.get("days_past_due") or item.get("age_days")
            age_bucket = str(item.get("age_bucket") or "").strip().lower()
            over_flag = item.get("over_threshold") is True

            has_age = txn_date is not None or age_days is not None or age_bucket or over_flag
            if amt is None or not has_age:
                invalid_count += 1
                continue

            is_over = False
            txn_date_str = None
            if txn_date is not None:
                is_over = txn_date < cutoff
                txn_date_str = txn_date.isoformat()
            elif isinstance(age_days, (int, float, str)):
                try:
                    is_over = int(age_days) >= int(threshold_days)
                except Exception:
                    is_over = False
            elif over_flag:
                is_over = True
            elif age_bucket:
                is_over = "61" in age_bucket or "90" in age_bucket or "over" in age_bucket

            if is_over:
                out.append(
                    {
                        "id": item.get("id") or item.get("txn_id") or "",
                        "name": item.get("name") or item.get("vendor") or item.get("customer") or "",
                        "txn_date": txn_date_str,
                        "amount": str(amt),
                        "age_bucket": item.get("age_bucket"),
                    }
                )
        return out, invalid_count

    def _summary_map(self, items: list[dict[str, Any]]) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for item in items:
            name = str(item.get("name") or item.get("vendor") or item.get("customer") or "").strip()
            amt = _parse_decimal(item.get("amount"))
            if not name or amt is None:
                continue
            out[name] = out.get(name, Decimal("0")) + amt
        return out

    def _diff_maps(
        self, detail_map: dict[str, Decimal], summary_map: dict[str, Decimal]
    ) -> list[dict[str, str]]:
        keys = sorted(set(detail_map) | set(summary_map))
        diffs: list[dict[str, str]] = []
        for key in keys:
            d = detail_map.get(key, Decimal("0"))
            s = summary_map.get(key, Decimal("0"))
            if d != s:
                diffs.append(
                    {
                        "name": key,
                        "detail_total": str(d),
                        "summary_total": str(s),
                        "difference": str(abs(d - s)),
                    }
                )
        return diffs
