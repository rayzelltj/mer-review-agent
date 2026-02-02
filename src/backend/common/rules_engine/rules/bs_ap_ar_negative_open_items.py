from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import ApArNegativeOpenItemsRuleConfig
from ..context import RuleContext
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


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
class BS_AP_AR_NEGATIVE_OPEN_ITEMS(Rule):
    rule_id = "BS-AP-AR-NEGATIVE-OPEN-ITEMS"
    rule_title = "Negative open AP/AR items identified"
    best_practices_reference = "Accounts Payable/Receivable"
    sources = ["QBO (Aged Payables/Receivables Detail)"]
    config_model = ApArNegativeOpenItemsRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, ApArNegativeOpenItemsRuleConfig)
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

        ap_detail = ctx.evidence.first(cfg.ap_detail_rows_evidence_type)
        ar_detail = ctx.evidence.first(cfg.ar_detail_rows_evidence_type)
        if ap_detail is None or ap_detail.amount is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary=f"Missing AP aging detail rows for {ctx.period_end.isoformat()}; cannot verify.",
                evidence_used=[ap_detail] if ap_detail else [],
                human_action="Provide AP aging detail report rows as of period end.",
            )
        if ar_detail is None or ar_detail.amount is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary=f"Missing AR aging detail rows for {ctx.period_end.isoformat()}; cannot verify.",
                evidence_used=[ar_detail] if ar_detail else [],
                human_action="Provide AR aging detail report rows as of period end.",
            )

        if cfg.require_evidence_as_of_date_match_period_end:
            if ap_detail.as_of_date is None or ap_detail.as_of_date != ctx.period_end:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=missing_status,
                    severity=severity_for_status(missing_status),
                    summary="AP aging detail as-of date is missing or does not match period end; cannot verify.",
                    evidence_used=[ap_detail],
                    human_action="Provide AP aging detail report as of the period end date.",
                )
            if ar_detail.as_of_date is None or ar_detail.as_of_date != ctx.period_end:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=missing_status,
                    severity=severity_for_status(missing_status),
                    summary="AR aging detail as-of date is missing or does not match period end; cannot verify.",
                    evidence_used=[ar_detail],
                    human_action="Provide AR aging detail report as of the period end date.",
                )

        ap_items = _items_from_meta(ap_detail.meta or {})
        ar_items = _items_from_meta(ar_detail.meta or {})
        if ap_items is None or ar_items is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Missing AP/AR aging detail items; cannot verify.",
                evidence_used=[ap_detail, ar_detail],
                human_action="Provide AP/AR aging detail items (with open balance) as of period end.",
            )

        ap_negatives = self._negative_open_items(ap_items)
        ar_negatives = self._negative_open_items(ar_items)

        has_negatives = bool(ap_negatives or ar_negatives)
        status = RuleStatus.NEEDS_REVIEW if has_negatives else RuleStatus.PASS

        summary = (
            "Negative open AP/AR items detected; review credits/overpayments."
            if has_negatives
            else "No negative open AP/AR items detected."
        )
        human_action = (
            "Investigate negative open balances (credits/overpayments) and document support."
            if has_negatives
            else None
        )

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=status,
            severity=severity_for_status(status),
            summary=summary,
            details=[
                RuleResultDetail(
                    key="ap_negative_open_items",
                    message="AP negative open items.",
                    values={
                        "period_end": ctx.period_end.isoformat(),
                        "negative_item_count": len(ap_negatives),
                        "negative_items": ap_negatives[:25],
                        "status": status.value,
                    },
                ),
                RuleResultDetail(
                    key="ar_negative_open_items",
                    message="AR negative open items.",
                    values={
                        "period_end": ctx.period_end.isoformat(),
                        "negative_item_count": len(ar_negatives),
                        "negative_items": ar_negatives[:25],
                        "status": status.value,
                    },
                ),
            ],
            evidence_used=[ap_detail, ar_detail],
            human_action=human_action,
        )

    def _negative_open_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            amt = _parse_decimal(item.get("open_balance"))
            if amt is None:
                continue
            if amt < 0:
                out.append(
                    {
                        "name": item.get("name") or item.get("vendor") or item.get("customer") or "",
                        "open_balance": str(amt),
                    }
                )
        return out
