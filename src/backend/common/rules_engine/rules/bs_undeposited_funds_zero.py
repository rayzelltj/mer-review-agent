from __future__ import annotations

from ..config import ZeroBalanceRuleConfig
from ..context import RuleContext, compute_allowed_variance, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, Severity, StatusOrdering
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_UNDEPOSITED_FUNDS_ZERO(Rule):
    rule_id = "BS-UNDEPOSITED-FUNDS-ZERO"
    rule_title = "Undeposited Funds should be zero at period end"
    best_practices_reference = "Bank reconciliations"
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
                severity=Severity.INFO,
                summary="Rule disabled by client configuration.",
            )

        if not cfg.accounts:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=cfg.default_severity,
                summary=f"Undeposited Funds account not configured for period end {ctx.period_end.isoformat()}.",
                human_action="Configure the Undeposited Funds account ref for this client.",
            )

        revenue_total = ctx.get_revenue_total()
        ordering = StatusOrdering.default()
        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []

        default_threshold_configured = (cfg.default_threshold.floor_amount != 0) or (
            cfg.default_threshold.pct_of_revenue != 0
        )
        has_any_threshold = default_threshold_configured or any(a.threshold is not None for a in cfg.accounts)

        for acct_cfg in cfg.accounts:
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
                    message="Undeposited Funds balance evaluated.",
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
                    },
                )
            )

        overall = ordering.worst(statuses)
        severity = {
            RuleStatus.PASS: cfg.pass_severity,
            RuleStatus.WARN: cfg.warn_severity,
            RuleStatus.FAIL: cfg.fail_severity,
            RuleStatus.NEEDS_REVIEW: cfg.default_severity,
            RuleStatus.NOT_APPLICABLE: cfg.not_applicable_severity,
        }[overall]

        exemplar = next((d for d in details if d.values.get("status") == overall.value), None)
        if overall == RuleStatus.PASS:
            summary = f"Undeposited Funds is exactly zero as of {ctx.period_end.isoformat()}."
        elif overall == RuleStatus.WARN and exemplar:
            summary = (
                f"Undeposited Funds is non-zero ({exemplar.values.get('balance')}) as of {ctx.period_end.isoformat()} "
                f"({exemplar.values.get('allowed_variance')} allowed); verify."
            )
        elif overall == RuleStatus.FAIL and exemplar:
            summary = (
                f"Undeposited Funds exceeds allowed variance ({exemplar.values.get('balance')} vs "
                f"{exemplar.values.get('allowed_variance')}) as of {ctx.period_end.isoformat()}."
            )
        elif overall == RuleStatus.NEEDS_REVIEW:
            summary = f"Missing data prevented evaluation as of {ctx.period_end.isoformat()}."
        else:
            summary = "Not applicable."

        human_action = None
        if overall in (RuleStatus.WARN, RuleStatus.FAIL, RuleStatus.NEEDS_REVIEW):
            human_action = (
                "Verify undeposited items, deposit timing, and explain any non-zero balance at period end; "
                "adjust tolerance if warranted."
            )
            if not has_any_threshold and overall != RuleStatus.PASS:
                human_action = (
                    f"{human_action} Note: no acceptable variance was configured (TBD); "
                    "set thresholds (floor and/or % of revenue)."
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
