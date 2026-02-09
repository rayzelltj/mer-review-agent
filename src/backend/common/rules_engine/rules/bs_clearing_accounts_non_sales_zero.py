from __future__ import annotations

from decimal import Decimal

from ..config import NonSalesClearingAccountsZeroRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, StatusOrdering, severity_for_status
from ..registry import register_rule
from ..rule import Rule


def _is_current_asset_type(account_type: str, current_asset_types: list[str]) -> bool:
    if not account_type:
        return False
    lowered = account_type.lower()
    return any(lowered == t.lower() for t in current_asset_types)


@register_rule
class BS_CLEARING_ACCOUNTS_NON_SALES_ZERO(Rule):
    rule_id = "BS-CLEARING-ACCOUNTS-NON-SALES-ZERO"
    rule_title = "Non-sales clearing accounts should be zero at period end"
    best_practices_reference = "Clearing accounts (non-sales)"
    sources = ["QBO"]
    config_model = NonSalesClearingAccountsZeroRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(
            self.rule_id, NonSalesClearingAccountsZeroRuleConfig
        )
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

        clearing_accounts = [
            acct
            for acct in ctx.balance_sheet.accounts
            if acct.account_ref
            and not acct.account_ref.startswith("report::")
            and acct.name
            and any(pat in (acct.name or "").lower() for pat in cfg.name_patterns)
        ]
        if not clearing_accounts:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary="No clearing accounts found on Balance Sheet.",
            )

        type_unknown = []
        non_sales_accounts = []
        for acct in clearing_accounts:
            if not acct.type:
                type_unknown.append(acct)
                continue
            if _is_current_asset_type(acct.type, cfg.current_asset_types):
                continue
            non_sales_accounts.append(acct)

        ordering = StatusOrdering.default()
        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []

        if type_unknown:
            statuses.append(missing_status)
            details.extend(
                [
                    RuleResultDetail(
                        key=acct.account_ref,
                        message="Clearing account missing account type; cannot classify sales vs non-sales.",
                        values={
                            "account_name": acct.name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                    for acct in type_unknown
                ]
            )

        if not non_sales_accounts:
            overall = ordering.worst(statuses)
            if overall == RuleStatus.NOT_APPLICABLE:
                overall = RuleStatus.NOT_APPLICABLE
            summary = (
                "No non-sales clearing accounts found on Balance Sheet."
                if overall == RuleStatus.NOT_APPLICABLE
                else "Missing data prevented evaluation of non-sales clearing accounts."
            )
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=overall,
                severity=severity_for_status(overall),
                summary=summary,
                details=details,
                human_action=(
                    "Provide account types for clearing accounts to classify sales vs non-sales."
                    if overall == missing_status
                    else None
                ),
            )

        for acct in non_sales_accounts:
            bal_q = quantize_amount(acct.balance, cfg.amount_quantize)
            status = RuleStatus.PASS if bal_q == Decimal("0") else RuleStatus.FAIL
            statuses.append(status)
            details.append(
                RuleResultDetail(
                    key=acct.account_ref,
                    message="Non-sales clearing account balance evaluated.",
                    values={
                        "account_name": acct.name,
                        "account_type": acct.type,
                        "period_end": ctx.period_end.isoformat(),
                        "balance": str(bal_q),
                        "status": status.value,
                    },
                )
            )

        overall = ordering.worst(statuses)
        if overall == RuleStatus.PASS:
            summary = f"All non-sales clearing accounts are zero as of {ctx.period_end.isoformat()}."
        elif overall == RuleStatus.FAIL:
            summary = (
                f"One or more non-sales clearing accounts are non-zero as of "
                f"{ctx.period_end.isoformat()}."
            )
        elif overall == RuleStatus.NEEDS_REVIEW:
            summary = f"Missing data prevented evaluation as of {ctx.period_end.isoformat()}."
        else:
            summary = "Not applicable."

        human_action = None
        if overall in (RuleStatus.FAIL, RuleStatus.NEEDS_REVIEW):
            human_action = (
                "Investigate non-sales clearing account balances and clear them to zero at period end."
            )

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=overall,
            severity=severity_for_status(overall),
            summary=summary,
            details=details,
            human_action=human_action,
        )
