from __future__ import annotations

from decimal import Decimal

from ..config import AccountThresholdOverride, ClearingAccountsZeroRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, StatusOrdering, severity_for_status
from ..registry import register_rule
from ..rule import Rule

PLATFORM_REVENUE_RATE = Decimal("0.10")
PRIOR_VARIANCE_RATE = Decimal("0.03")


def _platform_tokens(account_name: str) -> list[str]:
    stopwords = {
        "clearing",
        "account",
        "accounts",
        "bank",
        "funds",
        "undeposited",
        "fund",
    }
    tokens = [
        t.strip().lower()
        for t in account_name.replace("-", " ").replace("/", " ").split()
        if t.strip()
    ]
    return [t for t in tokens if t not in stopwords and len(t) >= 3]


def _platform_revenue_from_pnl(
    pnl, account_name: str
) -> tuple[Decimal | None, list[str]]:
    if pnl is None or not account_name:
        return None, []
    tokens = _platform_tokens(account_name)
    if not tokens:
        return None, []

    total = Decimal("0")
    matched = False
    for key, amount in (pnl.totals or {}).items():
        if not isinstance(key, str) or not key.startswith("income_line:"):
            continue
        line_name = key.split("income_line:", 1)[1].lower()
        if any(t in line_name for t in tokens):
            total += amount
            matched = True

    return (total if matched else None), tokens


def _is_sales_asset_type(account_type: str, current_asset_types: list[str]) -> bool:
    if not account_type:
        return False
    lowered = account_type.lower()
    if any(lowered == t.lower() for t in current_asset_types):
        return True
    return "asset" in lowered


def _latest_prior_snapshot(ctx: RuleContext):
    if not ctx.prior_balance_sheets:
        return None
    return max(
        (bs for bs in ctx.prior_balance_sheets if bs.as_of_date < ctx.period_end),
        default=None,
        key=lambda bs: bs.as_of_date,
    )


def _previous_month_variance_value(
    ctx: RuleContext,
    *,
    account_ref: str,
) -> tuple[Decimal, str | None, bool]:
    prior_snapshot = _latest_prior_snapshot(ctx)
    if prior_snapshot is None:
        return Decimal("0"), None, True

    for acct in prior_snapshot.accounts:
        if acct.account_ref == account_ref:
            return abs(acct.balance), prior_snapshot.as_of_date.isoformat(), False

    return Decimal("0"), prior_snapshot.as_of_date.isoformat(), True


@register_rule
class BS_CLEARING_ACCOUNTS_ZERO(Rule):
    rule_id = "BS-CLEARING-ACCOUNTS-ZERO"
    rule_title = "Sales clearing accounts should be within threshold at period end"
    best_practices_reference = "Clearing accounts (sales clearing tolerance)"
    sources = ["QBO"]
    config_model = ClearingAccountsZeroRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, ClearingAccountsZeroRuleConfig)
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
        type_unknown: list[AccountThresholdOverride] = []
        account_by_ref = {acct.account_ref: acct for acct in ctx.balance_sheet.accounts}
        name_by_ref = {acct.account_ref: acct.name for acct in ctx.balance_sheet.accounts}

        if cfg.accounts:
            for acct_cfg in cfg.accounts:
                acct = account_by_ref.get(acct_cfg.account_ref)
                resolved_name = (acct.name if acct else "") or acct_cfg.account_name
                if acct is None:
                    accounts_to_eval.append(
                        AccountThresholdOverride(
                            account_ref=acct_cfg.account_ref,
                            account_name=resolved_name,
                            threshold=acct_cfg.threshold,
                        )
                    )
                    continue
                if not acct.type:
                    type_unknown.append(
                        AccountThresholdOverride(
                            account_ref=acct_cfg.account_ref,
                            account_name=resolved_name,
                            threshold=acct_cfg.threshold,
                        )
                    )
                    continue
                if _is_sales_asset_type(acct.type, cfg.current_asset_types):
                    accounts_to_eval.append(
                        AccountThresholdOverride(
                            account_ref=acct_cfg.account_ref,
                            account_name=resolved_name,
                            threshold=acct_cfg.threshold,
                        )
                    )
        else:
            used_name_inference = True
            for acct in ctx.balance_sheet.accounts:
                if acct.account_ref.startswith("report::"):
                    continue
                if "clearing" not in (acct.name or "").lower():
                    continue
                if not acct.type:
                    type_unknown.append(
                        AccountThresholdOverride(
                            account_ref=acct.account_ref,
                            account_name=acct.name,
                        )
                    )
                    continue
                if not _is_sales_asset_type(acct.type, cfg.current_asset_types):
                    continue
                accounts_to_eval.append(
                    AccountThresholdOverride(
                        account_ref=acct.account_ref,
                        account_name=acct.name,
                    )
                )

        if type_unknown:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary=(
                    "Clearing accounts found but missing account type/subtype; cannot "
                    "confirm they are sales clearing accounts under assets."
                ),
                details=[
                    RuleResultDetail(
                        key=acct.account_ref,
                        message="Clearing account missing account type; cannot classify.",
                        values={
                            "account_name": acct.account_name,
                            "period_end": ctx.period_end.isoformat(),
                            "classification_rule": "sales clearing accounts must be under assets",
                            "status": missing_status.value,
                        },
                    )
                    for acct in type_unknown
                ],
                human_action=(
                    "Provide account types (via Chart of Accounts) so clearing accounts can be classified under assets."
                ),
            )

        if not accounts_to_eval:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No sales clearing accounts found for period end {ctx.period_end.isoformat()}.",
                human_action=(
                    "Confirm whether sales clearing accounts exist under assets and ensure account names include "
                    "their platform/sales-channel name."
                ),
            )

        ordering = StatusOrdering.default()
        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []

        for acct_cfg in accounts_to_eval:
            bal = ctx.get_account_balance(acct_cfg.account_ref)
            account_name = name_by_ref.get(acct_cfg.account_ref, "") or acct_cfg.account_name
            if bal is None:
                statuses.append(missing_status)
                details.append(
                    RuleResultDetail(
                        key=acct_cfg.account_ref,
                        message="Account not found in balance sheet snapshot.",
                        values={
                            "account_name": account_name,
                            "period_end": ctx.period_end.isoformat(),
                            "classification_rule": "sales clearing accounts must be under assets",
                            "status": missing_status.value,
                        },
                    )
                )
                continue

            platform_revenue, platform_tokens = _platform_revenue_from_pnl(
                ctx.profit_and_loss, account_name
            )
            previous_variance_value, previous_period_end, previous_variance_missing = (
                _previous_month_variance_value(
                    ctx,
                    account_ref=acct_cfg.account_ref,
                )
            )

            platform_component = (
                (abs(platform_revenue) * PLATFORM_REVENUE_RATE).copy_abs()
                if platform_revenue is not None
                else Decimal("0")
            )
            previous_component = (previous_variance_value * PRIOR_VARIANCE_RATE).copy_abs()
            allowed = platform_component + previous_component

            bal_q = quantize_amount(bal, cfg.amount_quantize)
            abs_bal = abs(bal_q)
            platform_component_q = quantize_amount(platform_component, cfg.amount_quantize)
            previous_variance_q = quantize_amount(previous_variance_value, cfg.amount_quantize)
            previous_component_q = quantize_amount(previous_component, cfg.amount_quantize)
            allowed_q = quantize_amount(allowed, cfg.amount_quantize)
            allowed_variance_calculation = (
                f"({PLATFORM_REVENUE_RATE} * abs({platform_revenue if platform_revenue is not None else Decimal('0')})) + "
                f"({PRIOR_VARIANCE_RATE} * abs({previous_variance_value})) = {allowed_q}"
            )
            platform_name_missing = len(platform_tokens) == 0
            platform_revenue_missing = platform_revenue is None

            review_comment = None
            if platform_name_missing:
                status = RuleStatus.NEEDS_REVIEW
                review_comment = (
                    "GENERIC CLEARING ACCOUNT: add specific platform/sales-channel name "
                    "(e.g., 'Etsy Clearing Account')."
                )
            elif platform_revenue_missing:
                status = RuleStatus.NEEDS_REVIEW
                review_comment = (
                    "No matching platform revenue line found in P&L for this clearing account name."
                )
            elif abs_bal == 0:
                status = RuleStatus.PASS
            else:
                status = RuleStatus.WARN if abs_bal <= allowed_q else RuleStatus.FAIL

            statuses.append(status)
            details.append(
                RuleResultDetail(
                    key=acct_cfg.account_ref,
                    message="Clearing account balance evaluated.",
                    values={
                        "account_name": account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "balance": str(bal_q),
                        "abs_balance": str(abs_bal),
                        "classification_rule": "sales clearing accounts must be under assets",
                        "variance_formula": (
                            "allowed_variance = (10% * abs(platform_revenue)) + "
                            "(3% * abs(previous_month_variance_value))"
                        ),
                        "platform_revenue_rate": str(PLATFORM_REVENUE_RATE),
                        "platform_revenue": str(platform_revenue) if platform_revenue is not None else None,
                        "platform_variance_component": str(platform_component_q),
                        "previous_month_variance_rate": str(PRIOR_VARIANCE_RATE),
                        "previous_month_variance_value": str(previous_variance_q),
                        "previous_month_variance_component": str(previous_component_q),
                        "previous_month_period_end": previous_period_end,
                        "previous_month_variance_missing": previous_variance_missing,
                        "allowed_variance": str(allowed_q),
                        "allowed_variance_calculation": allowed_variance_calculation,
                        "threshold_source": "platform_revenue_plus_previous_month_variance",
                        "platform_tokens": platform_tokens,
                        "platform_name_missing": platform_name_missing,
                        "platform_revenue_missing": platform_revenue_missing,
                        "review_comment": review_comment,
                        "status": status.value,
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
        elif overall == RuleStatus.NEEDS_REVIEW and exemplar:
            review_comment = exemplar.values.get("review_comment")
            if review_comment:
                summary = review_comment
            else:
                summary = (
                    f"One or more sales clearing accounts require review as of {ctx.period_end.isoformat()} "
                    "(missing platform name, mapping, or data)."
                )
        elif overall == RuleStatus.NEEDS_REVIEW:
            summary = (
                f"One or more sales clearing accounts require review as of {ctx.period_end.isoformat()} "
                "(missing platform name, mapping, or data)."
            )
        else:
            summary = "Not applicable."

        human_action = None
        if overall in (RuleStatus.WARN, RuleStatus.FAIL, RuleStatus.NEEDS_REVIEW):
            has_generic = any(d.values.get("platform_name_missing") for d in details)
            has_missing_mapping = any(d.values.get("platform_revenue_missing") for d in details)
            if has_generic:
                human_action = (
                    "GENERIC CLEARING ACCOUNT detected. Rename each clearing account to include its associated "
                    "platform/sales channel (e.g., Etsy, Shopify, Amazon)."
                )
            elif has_missing_mapping:
                human_action = (
                    "Ensure each clearing account name maps to a platform revenue line in P&L "
                    "(income_line:*), then re-run the variance check."
                )
            else:
                human_action = (
                    "Review non-zero sales clearing balances and reconcile them using "
                    "allowed_variance = 10% platform revenue + 3% previous-month variance value."
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
