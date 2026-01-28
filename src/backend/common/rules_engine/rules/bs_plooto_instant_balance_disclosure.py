from __future__ import annotations

from ..config import PlootoInstantBalanceDisclosureRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, Severity, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE(Rule):
    rule_id = "BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE"
    rule_title = "Plooto Instant live balance identified"
    best_practices_reference = "Plooto"
    sources = ["Plooto (evidence)", "QBO (Balance Sheet)"]
    config_model = PlootoInstantBalanceDisclosureRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, PlootoInstantBalanceDisclosureRuleConfig)
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

        if not cfg.account_ref:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=f"Plooto Instant account not configured for period end {ctx.period_end.isoformat()}.",
                human_action="Configure the QBO Balance Sheet account ref for Plooto Instant.",
            )

        bs_balance = ctx.get_account_balance(cfg.account_ref)
        if bs_balance is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Plooto Instant account not found in Balance Sheet snapshot as of {ctx.period_end.isoformat()}; "
                    "cannot verify."
                ),
                details=[
                    RuleResultDetail(
                        key=cfg.account_ref,
                        message="Account not found in balance sheet snapshot.",
                        values={
                            "account_name": cfg.account_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": RuleStatus.NEEDS_REVIEW.value,
                        },
                    )
                ],
                human_action="Confirm whether Plooto Instant exists in QBO and map the correct Balance Sheet account.",
            )

        evidence_item = ctx.evidence.first(cfg.evidence_type)
        if evidence_item is None or evidence_item.amount is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Missing Plooto Instant live balance evidence amount for {ctx.period_end.isoformat()}; "
                    "cannot verify."
                ),
                evidence_used=[evidence_item] if evidence_item else [],
                human_action=(
                    "Request/attach Plooto Instant balance evidence (or extracted amount) as of period end."
                ),
            )

        if cfg.require_evidence_as_of_date_match_period_end:
            # Accounting policy: date mismatch should be reviewed (e.g., evidence pulled after month-end).
            if evidence_item.as_of_date is None or evidence_item.as_of_date != ctx.period_end:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=RuleStatus.NEEDS_REVIEW,
                    severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                    summary=(
                        "Plooto Instant live balance evidence date is missing or does not match period end; "
                        "cannot verify."
                    ),
                    evidence_used=[evidence_item],
                    details=[
                        RuleResultDetail(
                            key=cfg.account_ref,
                            message="Evidence as-of date mismatch.",
                            values={
                                "account_name": cfg.account_name,
                                "period_end": ctx.period_end.isoformat(),
                                "evidence_as_of_date": evidence_item.as_of_date.isoformat()
                                if evidence_item.as_of_date is not None
                                else None,
                                "status": RuleStatus.NEEDS_REVIEW.value,
                            },
                        )
                    ],
                    human_action="Provide Plooto Instant live balance evidence as of the period end date.",
                )

        bs_q = quantize_amount(bs_balance, cfg.amount_quantize)
        evidence_q = quantize_amount(evidence_item.amount, cfg.amount_quantize)
        diff = abs(bs_q - evidence_q)

        # Policy: Plooto Instant should be zero, and the QBO balance should match the live balance exactly.
        if diff != 0:
            status = RuleStatus.FAIL
            severity = severity_for_status(status)
            summary = (
                f"Plooto Instant balance does not match QBO as of {ctx.period_end.isoformat()} (diff {diff})."
            )
            human_action = (
                "Verify the Plooto Instant live balance and reconcile it to QBO; correct postings or mapping."
            )
        elif bs_q != 0:
            status = RuleStatus.FAIL
            severity = severity_for_status(status)
            summary = f"Plooto Instant balance is non-zero as of {ctx.period_end.isoformat()} (balance {bs_q})."
            human_action = (
                "Investigate why Plooto Instant is non-zero at period end and correct/clear it; "
                "confirm with the client if needed."
            )
        else:
            status = RuleStatus.PASS
            severity = severity_for_status(status)
            summary = f"Plooto Instant balance is zero and matches QBO as of {ctx.period_end.isoformat()}."
            human_action = None

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=status,
            severity=severity,
            summary=summary,
            details=[
                RuleResultDetail(
                    key=cfg.account_ref,
                    message="Plooto Instant live balance compared to QBO Balance Sheet account.",
                    values={
                        "account_name": cfg.account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "bs_balance": str(bs_q),
                        "plooto_live_balance": str(evidence_q),
                        "difference": str(diff),
                        "evidence_type": cfg.evidence_type,
                        "evidence_as_of_date": evidence_item.as_of_date.isoformat()
                        if evidence_item.as_of_date is not None
                        else None,
                        "status": status.value,
                    },
                )
            ],
            evidence_used=[evidence_item],
            human_action=human_action,
        )
