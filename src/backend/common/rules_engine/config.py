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
    # NOTE: Severity is a fixed mapping from RuleStatus (firm policy). These fields are retained for backwards
    # compatibility with older client configs/cached catalogs, but rule evaluators should not read them.
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
    unconfigured_threshold_policy: RuleStatus = RuleStatus.NEEDS_REVIEW


class PettyCashMatchRuleConfig(RuleConfigBase):
    account_ref: str = ""
    account_name: str = ""
    evidence_type: str = "petty_cash_support"


class BankReconciledThroughPeriodEndRuleConfig(RuleConfigBase):
    # Default behavior is to infer bank/credit card scope from Balance Sheet account type/subtype.
    # Overrides are available for edge cases (include/exclude specific accounts).
    include_accounts: List[str] = Field(default_factory=list)
    exclude_accounts: List[str] = Field(default_factory=list)

    # Back-compat: older configs used `expected_accounts` as the explicit list of accounts to evaluate.
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


class UnclearedItemsInvestigatedAndFlaggedRuleConfig(RuleConfigBase):
    # Optional scope control. If set, missing any expected account snapshot triggers `missing_data_policy`.
    # If empty, the rule evaluates all provided reconciliation snapshots.
    expected_accounts: List[str] = Field(default_factory=list)

    # Flag uncleared items older than this many *calendar months* as of `ReconciliationSnapshot.statement_end_date`.
    # "More than 2 months old" means `txn_date < statement_end_date - 2 months` (strictly earlier).
    months_old_threshold: int = 2

    # Status to assign when stale uncleared items are found (typical: WARN; can be set to FAIL per client policy).
    stale_item_status: RuleStatus = RuleStatus.WARN

    # Limit the number of flagged items included in each detail payload.
    max_flagged_items_in_detail: int = 20


class PlootoInstantBalanceDisclosureRuleConfig(RuleConfigBase):
    # QBO Balance Sheet account ref that represents Plooto Instant balance in the books.
    account_ref: str = ""
    account_name: str = ""

    # Evidence item representing the Plooto Instant live balance as of period end (e.g., screenshot/export/manual extraction).
    evidence_type: str = "plooto_instant_live_balance"

    # If true, require the evidence item's `as_of_date` to equal `RuleContext.period_end`.
    # Date mismatches should be flagged for review (per policy).
    require_evidence_as_of_date_match_period_end: bool = True


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
