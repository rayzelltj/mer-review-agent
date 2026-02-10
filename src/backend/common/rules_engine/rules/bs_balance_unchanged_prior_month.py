from __future__ import annotations

from decimal import Decimal

from ..config import BalanceUnchangedPriorMonthRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_BALANCE_UNCHANGED_PRIOR_MONTH(Rule):
    rule_id = "BS-BALANCE-UNCHANGED-PRIOR-MONTH"
    rule_title = "Balances unchanged vs prior month"
    best_practices_reference = (
        "Significant balances should be reviewed monthly; unchanged balances can indicate missed updates."
    )
    sources = ["QBO (Balance Sheet)"]
    config_model = BalanceUnchangedPriorMonthRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, BalanceUnchangedPriorMonthRuleConfig)
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

        prior_snapshot = None
        if ctx.prior_balance_sheets:
            prior_snapshot = max(
                (bs for bs in ctx.prior_balance_sheets if bs.as_of_date < ctx.period_end),
                default=None,
                key=lambda bs: bs.as_of_date,
            )

        if prior_snapshot is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=(
                    f"Missing prior month Balance Sheet snapshot for {ctx.period_end.isoformat()}."
                ),
                human_action="Add the prior month Balance Sheet snapshot to enable this review.",
            )

        prior_balances: dict[str, Decimal] = {
            acct.account_ref: acct.balance for acct in prior_snapshot.accounts
        }

        unchanged_details: list[RuleResultDetail] = []
        for acct in ctx.balance_sheet.accounts:
            if acct.account_ref.startswith("report::"):
                continue
            prior_balance = prior_balances.get(acct.account_ref)
            if prior_balance is None:
                continue
            current_q = quantize_amount(acct.balance, cfg.amount_quantize)
            prior_q = quantize_amount(prior_balance, cfg.amount_quantize)
            if not cfg.include_zero_balances and current_q == Decimal("0"):
                continue
            if current_q != prior_q:
                continue
            unchanged_details.append(
                RuleResultDetail(
                    key=acct.account_ref,
                    message="SAME (unchanged vs prior month).",
                    values={
                        "account_name": acct.name,
                        "period_end": ctx.period_end.isoformat(),
                        "prior_period_end": prior_snapshot.as_of_date.isoformat(),
                        "current_balance": str(current_q),
                        "prior_balance": str(prior_q),
                        "status": RuleStatus.WARN.value,
                        "flag": "SAME",
                    },
                )
            )

        if not unchanged_details:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.PASS,
                severity=severity_for_status(RuleStatus.PASS),
                summary=(
                    f"No unchanged balances detected versus {prior_snapshot.as_of_date.isoformat()}."
                ),
            )

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=RuleStatus.WARN,
            severity=severity_for_status(RuleStatus.WARN),
            summary=(
                f"{len(unchanged_details)} balance(s) unchanged vs "
                f"{prior_snapshot.as_of_date.isoformat()}."
            ),
            details=unchanged_details,
            human_action="Confirm whether each unchanged balance is expected for the period.",
        )
