from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, Field

from .models import MissingDataPolicy, RuleStatus, Severity

T = TypeVar("T", bound=BaseModel)


class VarianceThreshold(BaseModel):
    floor_amount: Decimal = Decimal("0")
    pct_of_revenue: Decimal = Decimal("0")


class RuleConfigBase(BaseModel):
    enabled: bool = True
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.NEEDS_REVIEW
    # Severity defaults are intentionally conservative: WARN should surface for review, FAIL should be high urgency.
    pass_severity: Severity = Severity.INFO
    warn_severity: Severity = Severity.LOW
    fail_severity: Severity = Severity.HIGH
    default_severity: Severity = Severity.MEDIUM
    not_applicable_severity: Severity = Severity.INFO
    # Optional quantization for amount comparisons (e.g. Decimal("0.01") for cents). If unset, comparisons are exact.
    amount_quantize: Optional[Decimal] = None


class AccountThresholdOverride(BaseModel):
    account_ref: str
    account_name: str = ""
    threshold: Optional[VarianceThreshold] = None


class ZeroBalanceRuleConfig(RuleConfigBase):
    accounts: List[AccountThresholdOverride] = Field(default_factory=list)
    default_threshold: VarianceThreshold = Field(default_factory=VarianceThreshold)
    # If true, infer accounts by name match (rule-specific); prefer explicit config over inference.
    allow_name_inference: bool = False
    # Policy for non-zero balances when no thresholds are configured (TBD by business policy).
    unconfigured_threshold_policy: RuleStatus = RuleStatus.WARN


class PettyCashMatchRuleConfig(RuleConfigBase):
    account_ref: str = ""
    account_name: str = ""
    evidence_type: str = "petty_cash_support"


class BankReconciledThroughPeriodEndRuleConfig(RuleConfigBase):
    expected_accounts: List[str] = Field(default_factory=list)
    require_statement_end_date_gte_period_end: bool = True
    # Register balance as of period end must tie to the Balance Sheet balance (exact match).
    require_book_balance_as_of_period_end_ties_to_balance_sheet: bool = True
    # Statement ending balance must match a statement artifact/attachment (exact match).
    # Evidence items are expected to provide `statement_end_date`, `amount`, and `meta["account_ref"]`.
    require_statement_balance_matches_attachment: bool = True
    statement_balance_attachment_evidence_type: str = "statement_balance_attachment"
    # Statement ending balance (reconciliation report) must match the Balance Sheet balance (exact match).
    require_statement_balance_matches_balance_sheet: bool = True


class ClientRulesConfig(BaseModel):
    """Client-specific configuration for all rules.

    Rules pull their typed config via `get_rule_config`.
    """

    rules: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    def get_rule_config(
        self,
        rule_id: str,
        model: Type[T],
        default: Optional[T] = None,
    ) -> T:
        if rule_id not in self.rules:
            if default is not None:
                return default
            return model()  # type: ignore[call-arg]
        raw = self.rules.get(rule_id, {})
        return model.model_validate(raw)
