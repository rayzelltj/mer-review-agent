from __future__ import annotations

from decimal import Decimal

from ..config import InvestmentBalanceMatchRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_INVESTMENT_BALANCE_MATCH(Rule):
    rule_id = "BS-INVESTMENT-BALANCE-MATCH"
    rule_title = "Investment balance matches QBO and statement"
    best_practices_reference = (
        "Loans/investments schedules or statements should be available and reconciled monthly"
    )
    sources = ["Google Drive (investment statement)", "QBO (Balance Sheet)"]
    config_model = InvestmentBalanceMatchRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, InvestmentBalanceMatchRuleConfig)
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
                    summary=(
                        f"Investment account not found in Balance Sheet snapshot as of "
                        f"{ctx.period_end.isoformat()}."
                    ),
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
                    human_action=(
                        "Confirm whether the investment exists in QBO and map the correct investment account."
                    ),
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
                summary=f"No investment account found as of {ctx.period_end.isoformat()}.",
                human_action="Configure the investment account ref or name match to enable this rule.",
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
                    f"Multiple investment accounts matched for {ctx.period_end.isoformat()}; cannot verify."
                ),
                details=[
                    RuleResultDetail(
                        key=acct_ref,
                        message="Multiple investment accounts matched by name inference.",
                        values={
                            "account_name": acct_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": RuleStatus.NEEDS_REVIEW.value,
                            "inferred_by_name_match": True,
                        },
                    )
                    for acct_ref, acct_name, _ in accounts_to_eval
                ],
                human_action="Configure a specific investment account ref to evaluate this rule.",
            )

        evidence_item = ctx.evidence.first(cfg.evidence_type)
        if evidence_item is None or evidence_item.amount is None:
            bs_q = quantize_amount(accounts_to_eval[0][2], cfg.amount_quantize)
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Missing investment statement balance for {ctx.period_end.isoformat()}; cannot verify."
                ),
                details=[
                    RuleResultDetail(
                        key=accounts_to_eval[0][0],
                        message="Investment balance needs statement evidence to verify.",
                        values={
                            "account_name": accounts_to_eval[0][1],
                            "period_end": ctx.period_end.isoformat(),
                            "bs_balance": str(bs_q),
                            "evidence_type": cfg.evidence_type,
                            "status": RuleStatus.NEEDS_REVIEW.value,
                            "inferred_by_name_match": used_name_inference,
                            "missing_evidence": True,
                        },
                    )
                ],
                evidence_used=[evidence_item] if evidence_item else [],
                human_action="Request/attach the investment statement (or extracted balance) as of period end.",
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
                        "Investment statement as-of date is missing or does not match period end; "
                        "cannot verify."
                    ),
                    evidence_used=[evidence_item],
                    human_action="Provide an investment statement as of the period end date.",
                )

        bs_q = quantize_amount(accounts_to_eval[0][2], cfg.amount_quantize)
        evidence_q = quantize_amount(evidence_item.amount, cfg.amount_quantize)
        diff = abs(bs_q - evidence_q)

        if diff == 0:
            status = RuleStatus.PASS
            severity = severity_for_status(status)
            summary = f"Investment balance matches the statement as of {ctx.period_end.isoformat()}."
        else:
            status = RuleStatus.FAIL
            severity = severity_for_status(status)
            summary = (
                f"Investment balance does not match the statement as of {ctx.period_end.isoformat()} "
                f"(diff {diff})."
            )

        human_action = None
        if status != RuleStatus.PASS:
            human_action = (
                "Confirm the statement basis (cost vs market) and reconcile QBO if it should match."
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
                    message="Investment balance compared to statement.",
                    values={
                        "account_name": accounts_to_eval[0][1],
                        "period_end": ctx.period_end.isoformat(),
                        "bs_balance": str(bs_q),
                        "statement_balance": str(evidence_q),
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
