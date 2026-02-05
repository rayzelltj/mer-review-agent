from __future__ import annotations

from typing import Any

from ..config import WorkingPaperReconcilesRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


def _matches_patterns(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    return any(pat in lowered for pat in patterns)


def _evidence_account_match(evidence_meta: dict[str, Any], account_name: str) -> bool:
    match = evidence_meta.get("account_name_match")
    if isinstance(match, str) and match.strip():
        return match.strip().lower() in account_name.lower()
    return False


@register_rule
class BS_WORKING_PAPER_RECONCILES(Rule):
    rule_id = "BS-WORKING-PAPER-RECONCILES"
    rule_title = "Working paper balances reconcile to Balance Sheet"
    best_practices_reference = "Prepayments/Deferred Revenue/Accruals"
    sources = ["Working papers (schedules)", "QBO (Balance Sheet)"]
    config_model = WorkingPaperReconcilesRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, WorkingPaperReconcilesRuleConfig)
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

        in_scope = [
            acct
            for acct in ctx.balance_sheet.accounts
            if acct.name and _matches_patterns(acct.name, cfg.name_patterns)
        ]
        if not in_scope:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No in-scope working paper accounts found as of {ctx.period_end.isoformat()}.",
            )

        evidence_items = [e for e in ctx.evidence.items if e.evidence_type == cfg.evidence_type]
        if not evidence_items:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=f"Missing working paper balances for {ctx.period_end.isoformat()}; cannot verify.",
                human_action="Provide the working paper balances as of period end.",
            )

        if cfg.require_evidence_as_of_date_match_period_end:
            for item in evidence_items:
                if item.as_of_date is None or item.as_of_date != ctx.period_end:
                    return RuleResult(
                        rule_id=self.rule_id,
                        rule_title=self.rule_title,
                        best_practices_reference=self.best_practices_reference,
                        sources=self.sources,
                        status=RuleStatus.NEEDS_REVIEW,
                        severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                        summary=(
                            "Working paper as-of date is missing or does not match period end; cannot verify."
                        ),
                        evidence_used=[item],
                        human_action="Provide working paper balances as of the period end date.",
                    )

        if len(in_scope) > 1 and len(evidence_items) == 1:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary="Multiple in-scope accounts but only one working paper balance provided; cannot verify.",
                details=[
                    RuleResultDetail(
                        key=acct.account_ref,
                        message="In-scope account without clear working paper match.",
                        values={
                            "account_name": acct.name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": RuleStatus.NEEDS_REVIEW.value,
                        },
                    )
                    for acct in in_scope
                ],
                evidence_used=evidence_items,
                human_action="Provide account-specific working paper balances or map by account name.",
            )

        details: list[RuleResultDetail] = []
        evidence_used: list[Any] = []
        failures: list[str] = []

        for acct in in_scope:
            matched_item = None
            if len(evidence_items) == 1:
                matched_item = evidence_items[0]
            else:
                for item in evidence_items:
                    if _evidence_account_match(item.meta or {}, acct.name):
                        matched_item = item
                        break

            if matched_item is None or matched_item.amount is None:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=RuleStatus.NEEDS_REVIEW,
                    severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                    summary="Missing working paper balance for an in-scope account; cannot verify.",
                    details=[
                        RuleResultDetail(
                            key=acct.account_ref,
                            message="Working paper balance missing for account.",
                            values={
                                "account_name": acct.name,
                                "period_end": ctx.period_end.isoformat(),
                                "status": RuleStatus.NEEDS_REVIEW.value,
                            },
                        )
                    ],
                    evidence_used=evidence_items,
                    human_action="Provide a working paper balance for the in-scope account.",
                )

            evidence_used.append(matched_item)
            bs_q = quantize_amount(acct.balance, cfg.amount_quantize)
            evidence_q = quantize_amount(matched_item.amount, cfg.amount_quantize)
            diff = abs(bs_q - evidence_q)

            status = RuleStatus.PASS if diff == 0 else RuleStatus.FAIL
            if status == RuleStatus.FAIL:
                failures.append(acct.name)

            details.append(
                RuleResultDetail(
                    key=acct.account_ref,
                    message="Working paper balance compared to Balance Sheet.",
                    values={
                        "account_name": acct.name,
                        "period_end": ctx.period_end.isoformat(),
                        "bs_balance": str(bs_q),
                        "working_paper_balance": str(evidence_q),
                        "difference": str(diff),
                        "evidence_type": cfg.evidence_type,
                        "evidence_as_of_date": matched_item.as_of_date.isoformat()
                        if matched_item.as_of_date is not None
                        else None,
                        "working_paper_uri": matched_item.uri,
                        "status": status.value,
                    },
                )
            )

        final_status = RuleStatus.FAIL if failures else RuleStatus.PASS
        summary = (
            f"Working paper balances do not match Balance Sheet for {len(failures)} account(s)."
            if failures
            else f"Working paper balances reconcile to Balance Sheet as of {ctx.period_end.isoformat()}."
        )
        human_action = (
            "Reconcile working paper balances to the Balance Sheet and document adjustments."
            if failures
            else None
        )

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=final_status,
            severity=severity_for_status(final_status),
            summary=summary,
            details=details,
            evidence_used=evidence_used,
            human_action=human_action,
        )
