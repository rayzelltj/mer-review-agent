from __future__ import annotations

from ..config import AccountThresholdOverride, ZeroBalanceRuleConfig
from ..context import RuleContext, compute_allowed_variance, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, Severity, StatusOrdering, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_CLEARING_ACCOUNTS_ZERO(Rule):
    rule_id = "BS-CLEARING-ACCOUNTS-ZERO"
    rule_title = "Clearing accounts should be zero at period end"
    best_practices_reference = "Clearing accounts (a $0 balance)"
    sources = ["QBO"]
    config_model = ZeroBalanceRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, ZeroBalanceRuleConfig)
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

        accounts_to_eval: list[AccountThresholdOverride] = []
        used_name_inference = False
        if cfg.accounts:
            accounts_to_eval = list(cfg.accounts)
        elif cfg.allow_name_inference:
            used_name_inference = True
            for acct in ctx.balance_sheet.accounts:
                if "clearing" in (acct.name or "").lower():
                    accounts_to_eval.append(
                        AccountThresholdOverride(
                            account_ref=acct.account_ref,
                            account_name=acct.name,
                        )
                    )

        if not accounts_to_eval:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=f"No clearing accounts configured for period end {ctx.period_end.isoformat()}.",
                human_action=(
                    "Configure clearing account refs for this client and set acceptable variances per account "
                    "(recommended)."
                ),
            )

        revenue_total = ctx.get_revenue_total()
        ordering = StatusOrdering.default()
        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []

        default_threshold_configured = (cfg.default_threshold.floor_amount != 0) or (
            cfg.default_threshold.pct_of_revenue != 0
        )
        has_any_threshold = default_threshold_configured or any(
            a.threshold is not None for a in accounts_to_eval
        )

        for acct_cfg in accounts_to_eval:
            bal = ctx.get_account_balance(acct_cfg.account_ref)
            if bal is None:
                statuses.append(missing_status)
                details.append(
                    RuleResultDetail(
                        key=acct_cfg.account_ref,
                        message="Account not found in balance sheet snapshot.",
                        values={
                            "account_name": acct_cfg.account_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                )
                continue

            threshold = acct_cfg.threshold or cfg.default_threshold
            threshold_configured = default_threshold_configured or (acct_cfg.threshold is not None)
            allowed = compute_allowed_variance(threshold=threshold, revenue_total=revenue_total)
            bal_q = quantize_amount(bal, cfg.amount_quantize)
            abs_bal = abs(bal_q)
            allowed_q = quantize_amount(allowed, cfg.amount_quantize)

            if abs_bal == 0:
                status = RuleStatus.PASS
            elif not threshold_configured:
                status = cfg.unconfigured_threshold_policy
            else:
                status = RuleStatus.WARN if abs_bal <= allowed_q else RuleStatus.FAIL

            statuses.append(status)
            details.append(
                RuleResultDetail(
                    key=acct_cfg.account_ref,
                    message="Clearing account balance evaluated.",
                    values={
                        "account_name": acct_cfg.account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "balance": str(bal_q),
                        "abs_balance": str(abs_bal),
                        "allowed_variance": str(allowed_q),
                        "revenue_total": str(revenue_total) if revenue_total is not None else None,
                        "threshold_floor_amount": str(threshold.floor_amount),
                        "threshold_pct_of_revenue": str(threshold.pct_of_revenue),
                        "status": status.value,
                        "threshold_configured": threshold_configured,
                        "inferred_by_name_match": used_name_inference,
                    },
                )
            )

        overall = ordering.worst(statuses)
        n_accounts = len(accounts_to_eval)
        severity = severity_for_status(overall)

        exemplar = next((d for d in details if d.values.get("status") == overall.value), None)
        if overall == RuleStatus.PASS:
            summary = f"All {n_accounts} clearing account(s) are exactly zero as of {ctx.period_end.isoformat()}."
        elif overall == RuleStatus.WARN and exemplar:
            summary = (
                f"Clearing account '{exemplar.values.get('account_name','')}' is non-zero "
                f"({exemplar.values.get('balance')}) as of {ctx.period_end.isoformat()} "
                f"({exemplar.values.get('allowed_variance')} allowed); verify."
            )
        elif overall == RuleStatus.FAIL and exemplar:
            summary = (
                f"Clearing account '{exemplar.values.get('account_name','')}' exceeds allowed variance "
                f"({exemplar.values.get('balance')} vs {exemplar.values.get('allowed_variance')}) "
                f"as of {ctx.period_end.isoformat()}."
            )
        elif overall == RuleStatus.NEEDS_REVIEW:
            summary = f"Missing data prevented evaluation for one or more accounts as of {ctx.period_end.isoformat()}."
        else:
            summary = "Not applicable."

        human_action = None
        if overall in (RuleStatus.WARN, RuleStatus.FAIL, RuleStatus.NEEDS_REVIEW):
            human_action = (
                "Verify clearing account activity near period end and explain any non-zero balances; "
                "adjust tolerances per account if warranted."
            )
            if not has_any_threshold and overall != RuleStatus.PASS:
                human_action = (
                    f"{human_action} Note: no acceptable variance was configured (TBD); "
                    "set per-account thresholds (floor and/or % of revenue)."
                )
            if used_name_inference:
                human_action = f"{human_action} Note: accounts were inferred by name match ('clearing')."

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
