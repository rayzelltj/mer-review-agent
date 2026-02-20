from __future__ import annotations

from datetime import date
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


class ClearingAccountsZeroRuleConfig(ZeroBalanceRuleConfig):
    # QBO account types considered "current assets" for sales clearing accounts.
    current_asset_types: List[str] = Field(
        default_factory=lambda: [
            "Bank",
            "Accounts Receivable",
            "Other Current Asset",
            "Cash and Cash Equivalents",
        ]
    )


class PettyCashMatchRuleConfig(RuleConfigBase):
    account_ref: str = ""
    account_name: str = ""
    evidence_type: str = "petty_cash_support"


class BankReconciledThroughPeriodEndRuleConfig(RuleConfigBase):
    # Scope overrides (optional). Default scope is active Bank/Credit Card accounts from CoA evidence.
    include_accounts: List[str] = Field(default_factory=list)
    exclude_accounts: List[str] = Field(default_factory=list)

    # If provided, acts as explicit scope (after exclude filter).
    expected_accounts: List[str] = Field(default_factory=list)

    # Evidence types used by the new reconciliation equation flow.
    chart_of_accounts_evidence_type: str = "qbo_chart_of_accounts_bank_cc_active"
    trial_balance_evidence_type: str = "qbo_trial_balance_register_balance"
    transaction_list_evidence_type: str = "qbo_transaction_list_unreconciled"
    statement_balance_attachment_evidence_type: str = "statement_balance_attachment"

    # If CoA evidence is missing, allow fallback name heuristics for bank/cc identification.
    allow_fallback_name_heuristics_when_coa_missing: bool = True
    # Evaluate active accounts only from CoA evidence.
    require_active_accounts_only: bool = True

    # Legacy fields retained for compatibility with older configs.
    require_statement_end_date_gte_period_end: bool = True
    require_book_balance_as_of_period_end_ties_to_balance_sheet: bool = True
    require_statement_balance_matches_attachment: bool = True
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

    # Optional name matcher for inference when account_ref isn't configured.
    account_name_match: str = "Plooto Instant"
    allow_name_inference: bool = True

    # Deprecated: evidence fields retained for backward compatibility with older configs.
    evidence_type: str = "plooto_instant_live_balance"
    require_evidence_as_of_date_match_period_end: bool = True


class PlootoClearingZeroRuleConfig(RuleConfigBase):
    # QBO Balance Sheet account ref that represents Plooto Clearing in the books.
    account_ref: str = ""
    account_name: str = ""
    account_name_match: str = "Plooto Clearing"
    allow_name_inference: bool = True


class LoanBalanceMatchRuleConfig(RuleConfigBase):
    # QBO Balance Sheet account ref that represents the loan balance in the books.
    account_ref: str = ""
    account_name: str = ""
    account_name_match: str = "loan"
    allow_name_inference: bool = True

    # Evidence item representing the outstanding balance from the loan schedule.
    evidence_type: str = "loan_schedule_balance"
    require_evidence_as_of_date_match_period_end: bool = True


class InvestmentBalanceMatchRuleConfig(RuleConfigBase):
    # QBO Balance Sheet account ref that represents the investment balance in the books.
    account_ref: str = ""
    account_name: str = ""
    account_name_match: str = "investment"
    allow_name_inference: bool = True

    # Evidence item representing the closing balance from the investment statement.
    evidence_type: str = "investment_statement_balance"
    require_evidence_as_of_date_match_period_end: bool = True


class BalanceUnchangedPriorMonthRuleConfig(RuleConfigBase):
    include_zero_balances: bool = True


class ApSubledgerReconcilesRuleConfig(RuleConfigBase):
    # QBO Balance Sheet account refs to include in the AP total.
    account_refs: List[str] = Field(default_factory=list)
    account_name_match: str = "accounts payable"
    allow_name_inference: bool = True

    # Evidence items representing totals from QBO AP aging reports.
    summary_evidence_type: str = "ap_aging_summary_total"
    detail_evidence_type: str = "ap_aging_detail_total"
    require_evidence_as_of_date_match_period_end: bool = True


class ArSubledgerReconcilesRuleConfig(RuleConfigBase):
    # QBO Balance Sheet account refs to include in the AR total.
    account_refs: List[str] = Field(default_factory=list)
    account_name_match: str = "accounts receivable"
    allow_name_inference: bool = True

    # Evidence items representing totals from QBO AR aging reports.
    summary_evidence_type: str = "ar_aging_summary_total"
    detail_evidence_type: str = "ar_aging_detail_total"
    require_evidence_as_of_date_match_period_end: bool = True


class ApArItemsOlderThan60DaysRuleConfig(RuleConfigBase):
    # Evidence types for AP/AR aging reports (summary + detail).
    ap_summary_evidence_type: str = "ap_aging_summary_over_60"
    ap_detail_evidence_type: str = "ap_aging_detail_over_60"
    ar_summary_evidence_type: str = "ar_aging_summary_over_60"
    ar_detail_evidence_type: str = "ar_aging_detail_over_60"

    # If true, require evidence `as_of_date` to equal `RuleContext.period_end`.
    require_evidence_as_of_date_match_period_end: bool = True

    # Threshold in days for "older than".
    age_threshold_days: int = 60


class ApArNegativeOpenItemsRuleConfig(RuleConfigBase):
    ap_detail_rows_evidence_type: str = "ap_aging_detail_rows"
    ar_detail_rows_evidence_type: str = "ar_aging_detail_rows"
    require_evidence_as_of_date_match_period_end: bool = True


class ApArIntercompanyOrShareholderPaidRuleConfig(RuleConfigBase):
    # Evidence bundle of intercompany balances from other entities' Balance Sheets.
    evidence_type: str = "intercompany_balance_sheet"

    # Match patterns for intercompany accounts in the local Balance Sheet.
    name_patterns: List[str] = Field(
        default_factory=lambda: ["due to", "due from", "intercompany", "inter-company"]
    )

    # If true, only evaluate non-zero balances.
    non_zero_only: bool = True

    # Require evidence as-of date to match period end.
    require_evidence_as_of_date_match_period_end: bool = True


class ApArYearEndBatchAdjustmentsRuleConfig(RuleConfigBase):
    ap_detail_rows_evidence_type: str = "ap_aging_detail_rows"
    ar_detail_rows_evidence_type: str = "ar_aging_detail_rows"
    require_evidence_as_of_date_match_period_end: bool = True
    name_patterns: List[str] = Field(
        default_factory=lambda: [
            "yer supplier",
            "year-end review",
            "ye adj",
            "year end",
            "y/e",
        ]
    )


class ApArPaidAfterMonthEndNotedRuleConfig(RuleConfigBase):
    ap_detail_rows_evidence_type: str = "ap_aging_detail_rows"
    ar_detail_rows_evidence_type: str = "ar_aging_detail_rows"

    # If true, the period-end AP/AR detail evidence must have as_of_date == RuleContext.period_end.
    require_period_end_evidence_date_match: bool = True

    # Optional explicit follow-up date for comparison (e.g. review date). If omitted, latest as_of_date > period_end
    # is used for each stream independently.
    comparison_as_of_date: date | None = None

    # Status assigned when period-end items are absent from the follow-up report (inferred settled after month-end).
    settled_item_status: RuleStatus = RuleStatus.NEEDS_REVIEW

    # Max number of settled items returned in detail payloads.
    max_noted_items_in_detail: int = 25


class IntercompanyBalancesReconcileRuleConfig(RuleConfigBase):
    evidence_type: str = "intercompany_balance_sheet"
    name_patterns: List[str] = Field(
        default_factory=lambda: [
            "intercompany loan",
            "loan from",
            "loan to",
            "shareholder loan",
            "loan",
        ]
    )
    non_zero_only: bool = True
    require_evidence_as_of_date_match_period_end: bool = True


class WorkingPaperReconcilesRuleConfig(RuleConfigBase):
    evidence_type: str = "working_paper_balance"
    name_patterns: List[str] = Field(
        default_factory=lambda: ["prepaid", "unearned", "deferred", "deferred revenue", "accrual"]
    )
    require_evidence_as_of_date_match_period_end: bool = True


class FixedAssetRegisterReconcilesRuleConfig(RuleConfigBase):
    evidence_type: str = "fixed_asset_register_balance"
    require_evidence_as_of_date_match_period_end: bool = True

    # When multiple balance sheet accounts match an asset class by name, prefer "Total <asset class>" lines.
    prefer_total_balance_sheet_lines: bool = True


class FixedAssetCapitalizationThresholdRuleConfig(RuleConfigBase):
    kyc_evidence_type: str = "kyc_profile"
    fixed_asset_ledger_evidence_type: str = "qbo_fixed_asset_ledger_transactions"
    pnl_expense_monthly_evidence_type: str = "qbo_pnl_expense_monthly"

    abnormal_change_pct: Decimal = Decimal("0.10")
    capitalization_violation_status: RuleStatus = RuleStatus.FAIL
    abnormal_expense_change_status: RuleStatus = RuleStatus.WARN

    require_kyc_threshold_when_fixed_asset_increase: bool = True
    require_ledger_transactions_when_fixed_asset_increase: bool = True

    max_transactions_to_evaluate_per_account: int = 200
    max_flagged_expense_lines: int = 50
    ignore_expense_name_patterns: List[str] = Field(
        default_factory=lambda: [
            "payroll",
            "wages",
            "salary",
            "cogs",
            "cost of goods",
        ]
    )


class NonSalesClearingAccountsZeroRuleConfig(RuleConfigBase):
    name_patterns: List[str] = Field(default_factory=lambda: ["clearing"])
    current_asset_types: List[str] = Field(
        default_factory=lambda: [
            "Bank",
            "Accounts Receivable",
            "Other Current Asset",
            "Cash and Cash Equivalents",
        ]
    )


class TaxFilingsUpToDateRuleConfig(RuleConfigBase):
    tax_agencies_evidence_type: str = "tax_agencies"
    tax_returns_evidence_type: str = "tax_returns"
    exclude_agency_name_patterns: List[str] = Field(
        default_factory=lambda: ["no tax agency"]
    )
    delinquent_status: RuleStatus = RuleStatus.FAIL
    account_name_patterns: List[str] = Field(
        default_factory=lambda: [
            "gst/hst payable",
            "gst/hst suspense",
            "gst/hst suspence",
            "gst payable",
            "gst suspense",
            "gst suspence",
            "hst payable",
            "hst suspense",
            "hst suspence",
            "pst payable",
            "pst suspense",
            "pst suspence",
        ]
    )


class TaxPayableAndSuspenseReconcileRuleConfig(RuleConfigBase):
    tax_agencies_evidence_type: str = "tax_agencies"
    tax_returns_evidence_type: str = "tax_returns"
    tax_payments_evidence_type: str = "tax_payments"
    delinquent_status: RuleStatus = RuleStatus.FAIL
    account_name_patterns: List[str] = Field(
        default_factory=lambda: [
            "gst/hst payable",
            "gst/hst suspense",
            "gst/hst suspence",
            "gst payable",
            "gst suspense",
            "gst suspence",
            "hst payable",
            "hst suspense",
            "hst suspence",
            "pst payable",
            "pst suspense",
            "pst suspence",
        ]
    )
    refund_grace_days: int = 60


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
