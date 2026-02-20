from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


SuggestedSource = Literal["Drive", "QBO"]


@dataclass(frozen=True)
class EvidenceRequirementSpec:
    field_name: str
    suggested_source: SuggestedSource
    required_document: str
    adapter_hint: str | None = None


@dataclass(frozen=True)
class ResolvedEvidenceRequirement:
    evidence_type: str
    suggested_source: SuggestedSource
    required_document: str
    adapter_hint: str | None = None


RULE_EVIDENCE_REQUIREMENTS: dict[str, tuple[EvidenceRequirementSpec, ...]] = {
    "BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END": (
        EvidenceRequirementSpec(
            field_name="chart_of_accounts_evidence_type",
            suggested_source="QBO",
            required_document="Chart of Accounts with active Bank/Credit Card accounts.",
            adapter_hint="adapters.qbo.bank_cc_reconciliation.active_bank_cc_accounts_from_accounts_payload",
        ),
        EvidenceRequirementSpec(
            field_name="trial_balance_evidence_type",
            suggested_source="QBO",
            required_document="Trial Balance report with month-end register balances by account.",
            adapter_hint="adapters.qbo.bank_cc_reconciliation.trial_balance_register_balances_from_report",
        ),
        EvidenceRequirementSpec(
            field_name="transaction_list_evidence_type",
            suggested_source="QBO",
            required_document=(
                "Transaction List by Account report for each in-scope account including clear/reconcile status "
                "to compute S1/S2 unreconciled sums."
            ),
            adapter_hint="adapters.qbo.bank_cc_reconciliation.transaction_list_unreconciled_sums_from_report",
        ),
        EvidenceRequirementSpec(
            field_name="statement_balance_attachment_evidence_type",
            suggested_source="Drive",
            required_document="Bank statement or activity statement ending balance (per account).",
            adapter_hint="adapters.mock_evidence.evidence_manifest.evidence_bundle_from_manifest",
        ),
    ),
    # Backward compatibility alias.
    "BS-BANK-RECONCILED-THROUGH-PERIOD-END": (
        EvidenceRequirementSpec(
            field_name="chart_of_accounts_evidence_type",
            suggested_source="QBO",
            required_document="Chart of Accounts with active Bank/Credit Card accounts.",
            adapter_hint="adapters.qbo.bank_cc_reconciliation.active_bank_cc_accounts_from_accounts_payload",
        ),
        EvidenceRequirementSpec(
            field_name="trial_balance_evidence_type",
            suggested_source="QBO",
            required_document="Trial Balance report with month-end register balances by account.",
            adapter_hint="adapters.qbo.bank_cc_reconciliation.trial_balance_register_balances_from_report",
        ),
        EvidenceRequirementSpec(
            field_name="transaction_list_evidence_type",
            suggested_source="QBO",
            required_document=(
                "Transaction List by Account report for each in-scope account including clear/reconcile status "
                "to compute S1/S2 unreconciled sums."
            ),
            adapter_hint="adapters.qbo.bank_cc_reconciliation.transaction_list_unreconciled_sums_from_report",
        ),
        EvidenceRequirementSpec(
            field_name="statement_balance_attachment_evidence_type",
            suggested_source="Drive",
            required_document="Bank statement or activity statement ending balance (per account).",
            adapter_hint="adapters.mock_evidence.evidence_manifest.evidence_bundle_from_manifest",
        ),
    ),
    "BS-PETTY-CASH-MATCH": (
        EvidenceRequirementSpec(
            field_name="evidence_type",
            suggested_source="Drive",
            required_document="Petty cash support at period end (count sheet, ledger, or signed support).",
            adapter_hint="adapters.mock_evidence.evidence_manifest.evidence_bundle_from_manifest",
        ),
    ),
    "BS-LOAN-BALANCE-MATCH": (
        EvidenceRequirementSpec(
            field_name="evidence_type",
            suggested_source="Drive",
            required_document="Loan schedule or lender statement balance at period end.",
            adapter_hint="adapters.mock_evidence.evidence_manifest.evidence_bundle_from_manifest",
        ),
    ),
    "BS-INVESTMENT-BALANCE-MATCH": (
        EvidenceRequirementSpec(
            field_name="evidence_type",
            suggested_source="Drive",
            required_document="Investment statement closing balance at period end.",
            adapter_hint="adapters.mock_evidence.evidence_manifest.evidence_bundle_from_manifest",
        ),
    ),
    "BS-WORKING-PAPER-RECONCILES": (
        EvidenceRequirementSpec(
            field_name="evidence_type",
            suggested_source="Drive",
            required_document="Working paper schedule total at period end (prepaid/deferred/accrual).",
            adapter_hint="adapters.working_papers.prepaid_schedule.prepaid_schedule_to_evidence",
        ),
    ),
    "BS-FIXED-ASSET-REGISTER-RECONCILES": (
        EvidenceRequirementSpec(
            field_name="evidence_type",
            suggested_source="Drive",
            required_document=(
                "Depreciation schedule and/or fixed asset register with month-end closing balances by asset class."
            ),
            adapter_hint="adapters.working_papers.fixed_asset_register.depreciation_schedule_to_evidence",
        ),
    ),
    "BS-FIXED-ASSET-CAPITALIZATION-THRESHOLD": (
        EvidenceRequirementSpec(
            field_name="kyc_evidence_type",
            suggested_source="Drive",
            required_document=(
                "KYC/client policy document with a fixed-asset capitalization threshold (e.g., > $1,000)."
            ),
            adapter_hint="adapters.mock_evidence.evidence_manifest.evidence_bundle_from_manifest",
        ),
        EvidenceRequirementSpec(
            field_name="fixed_asset_ledger_evidence_type",
            suggested_source="QBO",
            required_document=(
                "Transaction List by Account for fixed asset accounts covering the current month."
            ),
            adapter_hint="adapters.qbo.fixed_assets.fixed_asset_ledger_transactions_from_report",
        ),
        EvidenceRequirementSpec(
            field_name="pnl_expense_monthly_evidence_type",
            suggested_source="QBO",
            required_document=(
                "Profit and Loss report summarized by month with expense-line detail for current and prior month."
            ),
            adapter_hint="adapters.qbo.profit_and_loss.expense_month_over_month_from_report",
        ),
    ),
    "BS-AP-SUBLEDGER-RECONCILES": (
        EvidenceRequirementSpec(
            field_name="summary_evidence_type",
            suggested_source="QBO",
            required_document="Aged payables summary report total as of period end.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="detail_evidence_type",
            suggested_source="QBO",
            required_document="Aged payables detail report total as of period end.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
    ),
    "BS-AR-SUBLEDGER-RECONCILES": (
        EvidenceRequirementSpec(
            field_name="summary_evidence_type",
            suggested_source="QBO",
            required_document="Aged receivables summary report total as of period end.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="detail_evidence_type",
            suggested_source="QBO",
            required_document="Aged receivables detail report total as of period end.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
    ),
    "BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS": (
        EvidenceRequirementSpec(
            field_name="ap_summary_evidence_type",
            suggested_source="QBO",
            required_document="AP aging summary over-threshold totals (older than threshold).",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="ap_detail_evidence_type",
            suggested_source="QBO",
            required_document="AP aging detail over-threshold totals and rows.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="ar_summary_evidence_type",
            suggested_source="QBO",
            required_document="AR aging summary over-threshold totals (older than threshold).",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="ar_detail_evidence_type",
            suggested_source="QBO",
            required_document="AR aging detail over-threshold totals and rows.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
    ),
    "BS-AP-AR-NEGATIVE-OPEN-ITEMS": (
        EvidenceRequirementSpec(
            field_name="ap_detail_rows_evidence_type",
            suggested_source="QBO",
            required_document="AP aging detail rows with open balances.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="ar_detail_rows_evidence_type",
            suggested_source="QBO",
            required_document="AR aging detail rows with open balances.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
    ),
    "BS-AP-AR-YEAR_END_BATCH_ADJUSTMENTS": (
        EvidenceRequirementSpec(
            field_name="ap_detail_rows_evidence_type",
            suggested_source="QBO",
            required_document="AP aging detail rows for year-end generic name checks.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="ar_detail_rows_evidence_type",
            suggested_source="QBO",
            required_document="AR aging detail rows for year-end generic name checks.",
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
    ),
    "BS-AP-AR-PAID-AFTER-MONTH-END-NOTED": (
        EvidenceRequirementSpec(
            field_name="ap_detail_rows_evidence_type",
            suggested_source="QBO",
            required_document=(
                "AP aging detail rows as of period end and as of review date to identify items settled "
                "after month-end."
            ),
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="ar_detail_rows_evidence_type",
            suggested_source="QBO",
            required_document=(
                "AR aging detail rows as of period end and as of review date to identify items settled "
                "after month-end."
            ),
            adapter_hint="adapters.qbo.aging_reports.aging_report_to_evidence",
        ),
    ),
    "BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID": (
        EvidenceRequirementSpec(
            field_name="evidence_type",
            suggested_source="QBO",
            required_document="Counterparty balance sheet balances for intercompany comparison.",
            adapter_hint="adapters.qbo.intercompany.intercompany_balance_sheets_to_evidence",
        ),
    ),
    "BS-INTERCOMPANY-BALANCES-RECONCILE": (
        EvidenceRequirementSpec(
            field_name="evidence_type",
            suggested_source="QBO",
            required_document="Counterparty balance sheet balances for intercompany loan comparison.",
            adapter_hint="adapters.qbo.intercompany.intercompany_balance_sheets_to_evidence",
        ),
    ),
    "BS-TAX-FILINGS-UP-TO-DATE": (
        EvidenceRequirementSpec(
            field_name="tax_agencies_evidence_type",
            suggested_source="QBO",
            required_document="Tax agency list with filing metadata.",
            adapter_hint="adapters.qbo.tax.tax_agencies_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="tax_returns_evidence_type",
            suggested_source="QBO",
            required_document="Tax return history with filing periods and file dates.",
            adapter_hint="adapters.qbo.tax.tax_returns_to_evidence",
        ),
    ),
    "BS-TAX-PAYABLE-AND-SUSPENSE-RECONCILE-TO-RETURN": (
        EvidenceRequirementSpec(
            field_name="tax_agencies_evidence_type",
            suggested_source="QBO",
            required_document="Tax agency list used to map tax accounts.",
            adapter_hint="adapters.qbo.tax.tax_agencies_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="tax_returns_evidence_type",
            suggested_source="QBO",
            required_document="Tax return history with net tax due by period.",
            adapter_hint="adapters.qbo.tax.tax_returns_to_evidence",
        ),
        EvidenceRequirementSpec(
            field_name="tax_payments_evidence_type",
            suggested_source="QBO",
            required_document="Tax payment/refund history through period end.",
            adapter_hint="adapters.qbo.tax.tax_payments_to_evidence",
        ),
    ),
}


def resolve_rule_evidence_requirements(
    rule_id: str,
    cfg: Any,
) -> list[ResolvedEvidenceRequirement]:
    specs = RULE_EVIDENCE_REQUIREMENTS.get(rule_id, ())
    resolved: list[ResolvedEvidenceRequirement] = []
    for spec in specs:
        value = getattr(cfg, spec.field_name, None)
        if not isinstance(value, str):
            continue
        evidence_type = value.strip()
        if not evidence_type:
            continue
        resolved.append(
            ResolvedEvidenceRequirement(
                evidence_type=evidence_type,
                suggested_source=spec.suggested_source,
                required_document=spec.required_document,
                adapter_hint=spec.adapter_hint,
            )
        )
    return resolved
