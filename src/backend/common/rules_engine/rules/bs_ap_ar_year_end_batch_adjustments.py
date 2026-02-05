from __future__ import annotations

from typing import Any

from ..config import ApArYearEndBatchAdjustmentsRuleConfig
from ..context import RuleContext
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


def _items_from_meta(meta: dict[str, Any]) -> list[dict[str, Any]] | None:
    items = meta.get("items")
    if items is None:
        return None
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict)]
    return None


@register_rule
class BS_AP_AR_YEAR_END_BATCH_ADJUSTMENTS(Rule):
    rule_id = "BS-AP-AR-YEAR_END_BATCH_ADJUSTMENTS"
    rule_title = "Year-end AP/AR batch adjustments not left as generic supplier/customer"
    best_practices_reference = "Accounts Payable/Receivable → Year End Adjustments"
    sources = ["QBO (Aged Payables/Receivables Detail)"]
    config_model = ApArYearEndBatchAdjustmentsRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, ApArYearEndBatchAdjustmentsRuleConfig)
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

        if ap_detail is None and ar_detail is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No AP/AR aging detail evidence for {ctx.period_end.isoformat()}; not applicable.",
            )

        if cfg.require_evidence_as_of_date_match_period_end:
            if ap_detail is not None and (ap_detail.as_of_date is None or ap_detail.as_of_date != ctx.period_end):
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=RuleStatus.NOT_APPLICABLE,
                    severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                    summary="AP aging detail as-of date missing or does not match period end; not applicable.",
                    evidence_used=[ap_detail],
                )
            if ar_detail is not None and (ar_detail.as_of_date is None or ar_detail.as_of_date != ctx.period_end):
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=RuleStatus.NOT_APPLICABLE,
                    severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                    summary="AR aging detail as-of date missing or does not match period end; not applicable.",
                    evidence_used=[ar_detail],
                )

        patterns = [p.strip().lower() for p in (cfg.name_patterns or []) if str(p).strip()]

        ap_items = _items_from_meta(ap_detail.meta or {}) if ap_detail is not None else []
        ar_items = _items_from_meta(ar_detail.meta or {}) if ar_detail is not None else []
        if (ap_detail is not None and ap_items is None) or (ar_detail is not None and ar_items is None):
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary="AP/AR aging detail items missing; not applicable.",
                evidence_used=[i for i in [ap_detail, ar_detail] if i is not None],
            )

        ap_flagged = self._find_generic_names(ap_items, patterns)
        ar_flagged = self._find_generic_names(ar_items, patterns)

        has_flagged = bool(ap_flagged or ar_flagged)
        status = RuleStatus.NEEDS_REVIEW if has_flagged else RuleStatus.PASS
        summary = (
            "Generic year-end AP/AR batch adjustment names detected; review required."
            if has_flagged
            else "No generic year-end AP/AR batch adjustment names detected."
        )
        human_action = (
            "Replace generic year-end adjustment names with proper supplier/customer breakdown and clear items."
            if has_flagged
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
                    key="ap_generic_names",
                    message="AP aging detail generic year-end names.",
                    values={
                        "period_end": ctx.period_end.isoformat(),
                        "flagged_count": len(ap_flagged),
                        "flagged_items": ap_flagged[:25],
                        "status": status.value,
                    },
                ),
                RuleResultDetail(
                    key="ar_generic_names",
                    message="AR aging detail generic year-end names.",
                    values={
                        "period_end": ctx.period_end.isoformat(),
                        "flagged_count": len(ar_flagged),
                        "flagged_items": ar_flagged[:25],
                        "status": status.value,
                    },
                ),
            ],
            evidence_used=[i for i in [ap_detail, ar_detail] if i is not None],
            human_action=human_action,
        )

    def _find_generic_names(self, items: list[dict[str, Any]], patterns: list[str]) -> list[dict[str, str]]:
        flagged = []
        for item in items:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            lname = name.lower()
            if any(p in lname for p in patterns) or lname.startswith("ye ") or lname.startswith("y/e ") or lname.startswith("year end"):
                flagged.append({"name": name})
        return flagged
