from __future__ import annotations

from decimal import Decimal

from ..config import PlootoClearingZeroRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_PLOOTO_CLEARING_ZERO(Rule):
    rule_id = "BS-PLOOTO-CLEARING-ZERO"
    rule_title = "Plooto Clearing should be zero at period end"
    best_practices_reference = "Plooto"
    sources = ["QBO (Balance Sheet)"]
    config_model = PlootoClearingZeroRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, PlootoClearingZeroRuleConfig)
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
                    status=missing_status,
                    severity=severity_for_status(missing_status),
                    summary=(
                        f"Plooto Clearing account not found in Balance Sheet snapshot as of "
                        f"{ctx.period_end.isoformat()}; cannot verify."
                    ),
                    details=[
                        RuleResultDetail(
                            key=cfg.account_ref,
                            message="Account not found in balance sheet snapshot.",
                            values={
                                "account_name": cfg.account_name,
                                "period_end": ctx.period_end.isoformat(),
                                "status": missing_status.value,
                            },
                        )
                    ],
                    human_action="Confirm whether Plooto Clearing exists in QBO and map the correct Balance Sheet account.",
                )
            accounts_to_eval = [(cfg.account_ref, cfg.account_name, bs_balance)]
        elif cfg.allow_name_inference:
            used_name_inference = True
            name_match = (cfg.account_name_match or "Plooto Clearing").lower()
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
                summary=f"No Plooto Clearing account found as of {ctx.period_end.isoformat()}.",
            )

        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []

        for account_ref, account_name, balance in accounts_to_eval:
            bal_q = quantize_amount(balance, cfg.amount_quantize)
            status = RuleStatus.PASS if bal_q == 0 else RuleStatus.FAIL
            statuses.append(status)
            details.append(
                RuleResultDetail(
                    key=account_ref,
                    message="Plooto Clearing balance evaluated.",
                    values={
                        "account_name": account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "balance": str(bal_q),
                        "status": status.value,
                        "inferred_by_name_match": used_name_inference,
                    },
                )
            )

        overall = RuleStatus.FAIL if any(s == RuleStatus.FAIL for s in statuses) else RuleStatus.PASS
        severity = severity_for_status(overall)

        exemplar = next((d for d in details if d.values.get("status") == RuleStatus.FAIL.value), None)
        if overall == RuleStatus.PASS:
            summary = f"Plooto Clearing balance is zero as of {ctx.period_end.isoformat()}."
            human_action = None
        else:
            if exemplar:
                summary = (
                    f"Plooto Clearing balance is non-zero as of {ctx.period_end.isoformat()} "
                    f"(balance {exemplar.values.get('balance')})."
                )
            else:
                summary = f"Plooto Clearing balance is non-zero as of {ctx.period_end.isoformat()}."
            human_action = (
                "Investigate Plooto Clearing activity near period end and clear any non-zero balance."
            )

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=overall,
            severity=severity,
            summary=summary,
            details=details,
            human_action=human_action,
        )
