from __future__ import annotations

from decimal import Decimal

from ..config import LoanBalanceMatchRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_LOAN_BALANCE_MATCH(Rule):
    rule_id = "BS-LOAN-BALANCE-MATCH"
    rule_title = "Loan balance matches QBO and loan schedule"
    best_practices_reference = (
        "Loans/investments schedules or statements should be available and reconciled monthly"
    )
    sources = ["Google Drive (loan schedule)", "QBO (Balance Sheet)"]
    config_model = LoanBalanceMatchRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, LoanBalanceMatchRuleConfig)
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

        accounts_to_eval: list[tuple[str, str, Decimal]] = []
        used_name_inference = False

        if cfg.account_ref:
            bs_balance = ctx.get_account_balance(cfg.account_ref)
            if bs_balance is None:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=RuleStatus.NOT_APPLICABLE,
                    severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                    summary=f"Loan account not found in Balance Sheet snapshot as of {ctx.period_end.isoformat()}.",
                    details=[
                        RuleResultDetail(
                            key=cfg.account_ref,
                            message="Account not found in balance sheet snapshot.",
                            values={
                                "account_name": cfg.account_name,
                                "period_end": ctx.period_end.isoformat(),
                                "status": RuleStatus.NOT_APPLICABLE.value,
                            },
                        )
                    ],
                    human_action="Confirm whether the loan exists in QBO and map the correct loan account.",
                )
            accounts_to_eval = [(cfg.account_ref, cfg.account_name, bs_balance)]
        elif cfg.allow_name_inference and cfg.account_name_match:
            used_name_inference = True
            name_match = cfg.account_name_match.lower()
            for acct in ctx.balance_sheet.accounts:
                if name_match in (acct.name or "").lower():
                    accounts_to_eval.append((acct.account_ref, acct.name, acct.balance))

        if not accounts_to_eval:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No loan account found as of {ctx.period_end.isoformat()}.",
                human_action="Configure the loan account ref or name match to enable this rule.",
            )
        if len(accounts_to_eval) > 1:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Multiple loan accounts matched for {ctx.period_end.isoformat()}; cannot verify."
                ),
                details=[
                    RuleResultDetail(
                        key=acct_ref,
                        message="Multiple loan accounts matched by name inference.",
                        values={
                            "account_name": acct_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": RuleStatus.NEEDS_REVIEW.value,
                            "inferred_by_name_match": True,
                        },
                    )
                    for acct_ref, acct_name, _ in accounts_to_eval
                ],
                human_action="Configure a specific loan account ref to evaluate this rule.",
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
                    f"Missing loan schedule balance for {ctx.period_end.isoformat()}; cannot verify."
                ),
                evidence_used=[evidence_item] if evidence_item else [],
                human_action="Request/attach the loan schedule (or extracted balance) as of period end.",
            )

        if cfg.require_evidence_as_of_date_match_period_end:
            if evidence_item.as_of_date is None or evidence_item.as_of_date != ctx.period_end:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=RuleStatus.NEEDS_REVIEW,
                    severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                    summary=(
                        "Loan schedule as-of date is missing or does not match period end; cannot verify."
                    ),
                    evidence_used=[evidence_item],
                    human_action="Provide a loan schedule as of the period end date.",
                )

        bs_q = quantize_amount(accounts_to_eval[0][2], cfg.amount_quantize)
        evidence_q = quantize_amount(evidence_item.amount, cfg.amount_quantize)
        diff = abs(bs_q - evidence_q)

        if diff == 0:
            status = RuleStatus.PASS
            severity = severity_for_status(status)
            summary = f"Loan balance matches the schedule as of {ctx.period_end.isoformat()}."
        else:
            status = RuleStatus.FAIL
            severity = severity_for_status(status)
            summary = f"Loan balance does not match the schedule as of {ctx.period_end.isoformat()} (diff {diff})."

        human_action = None
        if status != RuleStatus.PASS:
            human_action = (
                "Verify the loan schedule balance (principal only if applicable) and reconcile QBO."
            )

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
                    key=accounts_to_eval[0][0],
                    message="Loan balance compared to loan schedule.",
                    values={
                        "account_name": accounts_to_eval[0][1],
                        "period_end": ctx.period_end.isoformat(),
                        "bs_balance": str(bs_q),
                        "schedule_balance": str(evidence_q),
                        "difference": str(diff),
                        "evidence_type": cfg.evidence_type,
                        "evidence_as_of_date": evidence_item.as_of_date.isoformat()
                        if evidence_item.as_of_date is not None
                        else None,
                        "status": status.value,
                        "inferred_by_name_match": used_name_inference,
                    },
                )
            ],
            evidence_used=[evidence_item],
            human_action=human_action,
        )
