from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..config import BankReconciledThroughPeriodEndRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import (
    AccountBalance,
    ReconciliationSnapshot,
    RuleResult,
    RuleResultDetail,
    RuleStatus,
    Severity,
    StatusOrdering,
    severity_for_status,
)
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_BANK_RECONCILED_THROUGH_PERIOD_END(Rule):
    rule_id = "BS-BANK-RECONCILED-THROUGH-PERIOD-END"
    rule_title = "Bank/credit card accounts reconciled through statement date"
    best_practices_reference = "Bank reconciliations → Banks and Credit cards"
    sources = ["QBO (reports/exports)", "Bank statements (evidence)"]
    config_model = BankReconciledThroughPeriodEndRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(
            self.rule_id, BankReconciledThroughPeriodEndRuleConfig
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

        inferred_refs, infer_detail = self._infer_scope_from_balance_sheet(ctx)
        if inferred_refs is None and not cfg.expected_accounts:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Cannot determine bank/credit card reconciliation scope for {ctx.period_end.isoformat()}; "
                    "account type/subtype data is missing."
                ),
                details=[infer_detail] if infer_detail is not None else [],
                human_action="Ensure the adapter provides Balance Sheet account type/subtype to infer bank/cc scope.",
            )

        required_refs = self._determine_scope(ctx, cfg, inferred_refs or [])
        if not required_refs:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No bank/credit card accounts in-scope as of {ctx.period_end.isoformat()}.",
            )

        ordering = StatusOrdering.default()

        recs = list(ctx.reconciliations)
        name_by_ref = {a.account_ref: a.name for a in ctx.balance_sheet.accounts}
        bs_balance_by_ref = {a.account_ref: a.balance for a in ctx.balance_sheet.accounts}
        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []
        if infer_detail is not None:
            statuses.append(RuleStatus.NEEDS_REVIEW)
            details.append(infer_detail)

        scope_check_status, scope_check_detail = self._check_maintenance_count(
            ctx, cfg, inferred_refs
        )
        if scope_check_status is not None and scope_check_detail is not None:
            statuses.append(scope_check_status)
            details.append(scope_check_detail)

        for account_ref in required_refs:
            account_name = name_by_ref.get(account_ref, "")
            candidates = [r for r in recs if r.account_ref == account_ref]
            if not candidates:
                statuses.append(missing_status)
                details.append(
                    RuleResultDetail(
                        key=account_ref,
                        message="Missing reconciliation snapshot for this account.",
                        values={
                            "account_name": account_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                            "expected_from_maintenance": True,
                        },
                    )
                )
                continue

            latest = max(
                candidates,
                key=lambda r: r.statement_end_date or date.min,
            )
            bs_balance = bs_balance_by_ref.get(account_ref)
            status, detail = self._evaluate_one(
                ctx,
                latest,
                cfg,
                balance_sheet_balance=bs_balance,
                account_name_fallback=account_name,
            )
            statuses.append(status)
            details.append(detail)

        overall = ordering.worst(statuses)
        severity = severity_for_status(overall)

        exemplar = next((d for d in details if d.values.get("status") == overall.value), None)
        if overall == RuleStatus.PASS:
            summary = (
                f"All {len(required_refs)} account(s) are reconciled through {ctx.period_end.isoformat()} "
                "and tie out exactly."
            )
        elif overall == RuleStatus.FAIL and exemplar:
            if exemplar.key == "scope_count":
                summary = (
                    "Maintenance bank/cc account count does not match Balance Sheet bank/cc count "
                    f"as of {ctx.period_end.isoformat()}."
                )
            else:
                summary = (
                    f"Account '{exemplar.values.get('account_name','')}' is not reconciled through period end "
                    f"or fails tie-out as of {ctx.period_end.isoformat()}."
                )
        elif overall == RuleStatus.NEEDS_REVIEW:
            summary = f"Missing data prevented evaluation for one or more accounts as of {ctx.period_end.isoformat()}."
        else:
            summary = "Not applicable."

        human_action = None
        if overall in (RuleStatus.WARN, RuleStatus.FAIL, RuleStatus.NEEDS_REVIEW):
            human_action = (
                "Verify reconciliation status through MER period end, confirm statement ending balances against "
                "bank statements, and tie out register/book balances to the Balance Sheet; explain or correct "
                "any variances."
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

    def _evaluate_one(
        self,
        ctx: RuleContext,
        rec: ReconciliationSnapshot,
        cfg: BankReconciledThroughPeriodEndRuleConfig,
        *,
        balance_sheet_balance: Decimal | None,
        account_name_fallback: str,
    ) -> tuple[RuleStatus, RuleResultDetail]:
        account_name = rec.account_name or account_name_fallback
        missing_status = RuleStatus(cfg.missing_data_policy.value)
        if rec.statement_end_date is None:
            return (
                missing_status,
                RuleResultDetail(
                    key=rec.account_ref,
                    message="Missing statement end date; cannot verify reconciliation through period end.",
                    values={
                        "account_name": account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "status": missing_status.value,
                    },
                ),
            )

        if cfg.require_statement_end_date_gte_period_end and rec.statement_end_date < ctx.period_end:
            return (
                RuleStatus.FAIL,
                RuleResultDetail(
                    key=rec.account_ref,
                    message="Statement end date is before MER period end; not reconciled through period end.",
                    values={
                        "account_name": account_name,
                        "statement_end_date": rec.statement_end_date.isoformat(),
                        "period_end": ctx.period_end.isoformat(),
                        "status": RuleStatus.FAIL.value,
                    },
                ),
            )

        if rec.statement_ending_balance is None:
            return (
                missing_status,
                RuleResultDetail(
                    key=rec.account_ref,
                    message="Missing statement ending balance; cannot tie out.",
                    values={
                        "account_name": account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "statement_end_date": rec.statement_end_date.isoformat(),
                        "status": missing_status.value,
                    },
                ),
            )

        if rec.book_balance_as_of_statement_end is None:
            return (
                missing_status,
                RuleResultDetail(
                    key=rec.account_ref,
                    message="Missing book/register balance as of statement end date; cannot tie out.",
                    values={
                        "account_name": account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "statement_end_date": rec.statement_end_date.isoformat(),
                        "statement_ending_balance": str(rec.statement_ending_balance),
                        "status": missing_status.value,
                    },
                ),
            )

        statement_end_q = quantize_amount(rec.book_balance_as_of_statement_end, cfg.amount_quantize)
        statement_bal_q = quantize_amount(rec.statement_ending_balance, cfg.amount_quantize)
        statement_diff = abs(statement_end_q - statement_bal_q)

        if statement_diff == 0:
            statement_status = RuleStatus.PASS
        else:
            statement_status = RuleStatus.FAIL

        statuses = [statement_status]
        period_end_status: RuleStatus | None = None
        period_end_diff: Decimal | None = None
        attachment_status: RuleStatus | None = None
        attachment_diff: Decimal | None = None
        attachment_amount: Decimal | None = None
        attachment_statement_end_date: date | None = None
        attachment_uri: str | None = None
        statement_balance_matches_bs_status: RuleStatus | None = None
        statement_balance_matches_bs_diff: Decimal | None = None

        # Required per policy: register balance as of period end must match Balance Sheet.
        if True:
            if balance_sheet_balance is None:
                period_end_status = missing_status
            elif rec.book_balance_as_of_period_end is None:
                period_end_status = missing_status
            else:
                bs_q = quantize_amount(balance_sheet_balance, cfg.amount_quantize)
                book_pe_q = quantize_amount(rec.book_balance_as_of_period_end, cfg.amount_quantize)
                period_end_diff = abs(book_pe_q - bs_q)
                if period_end_diff == 0:
                    period_end_status = RuleStatus.PASS
                else:
                    period_end_status = RuleStatus.FAIL
            statuses.append(period_end_status)

        if cfg.require_statement_balance_matches_balance_sheet:
            if balance_sheet_balance is None:
                statement_balance_matches_bs_status = missing_status
            else:
                bs_q = quantize_amount(balance_sheet_balance, cfg.amount_quantize)
                statement_balance_matches_bs_diff = abs(statement_bal_q - bs_q)
                statement_balance_matches_bs_status = (
                    RuleStatus.PASS if statement_balance_matches_bs_diff == 0 else RuleStatus.FAIL
                )
            statuses.append(statement_balance_matches_bs_status)

        # Required per policy: statement ending balance must match attachment (bank statement/activity statement).
        if True:
            evidence_item = None
            for item in ctx.evidence.items:
                if item.evidence_type != cfg.statement_balance_attachment_evidence_type:
                    continue
                if item.meta.get("account_ref") != rec.account_ref:
                    continue
                evidence_item = item
                break

            if evidence_item is None:
                attachment_status = missing_status
            elif evidence_item.amount is None:
                attachment_status = missing_status
            else:
                attachment_amount = quantize_amount(evidence_item.amount, cfg.amount_quantize)
                attachment_statement_end_date = evidence_item.statement_end_date
                attachment_uri = evidence_item.uri

                if (
                    attachment_statement_end_date is not None
                    and rec.statement_end_date is not None
                    and attachment_statement_end_date != rec.statement_end_date
                ):
                    attachment_status = RuleStatus.FAIL
                else:
                    attachment_diff = abs(statement_bal_q - attachment_amount)
                    attachment_status = RuleStatus.PASS if attachment_diff == 0 else RuleStatus.FAIL

            statuses.append(attachment_status)

        status = StatusOrdering.default().worst([s for s in statuses if s is not None])

        return (
            status,
            RuleResultDetail(
                key=rec.account_ref,
                message="Account reconciliation tie-out evaluated.",
                values={
                    "account_name": account_name,
                    "period_end": ctx.period_end.isoformat(),
                    "statement_end_date": rec.statement_end_date.isoformat(),
                    "statement_ending_balance": str(statement_bal_q),
                    "book_balance_as_of_statement_end": str(statement_end_q),
                    "statement_tie_difference": str(statement_diff),
                    "statement_tie_status": statement_status.value,
                    "require_book_balance_as_of_period_end_ties_to_balance_sheet": True,
                    "balance_sheet_balance": str(quantize_amount(balance_sheet_balance, cfg.amount_quantize))
                    if balance_sheet_balance is not None
                    else None,
                    "book_balance_as_of_period_end": str(
                        quantize_amount(rec.book_balance_as_of_period_end, cfg.amount_quantize)
                    )
                    if rec.book_balance_as_of_period_end is not None
                    else None,
                    "period_end_tie_difference": str(period_end_diff) if period_end_diff is not None else None,
                    "period_end_tie_status": period_end_status.value if period_end_status is not None else None,
                    "require_statement_balance_matches_balance_sheet": cfg.require_statement_balance_matches_balance_sheet,
                    "statement_balance_matches_balance_sheet_difference": str(statement_balance_matches_bs_diff)
                    if statement_balance_matches_bs_diff is not None
                    else None,
                    "statement_balance_matches_balance_sheet_status": statement_balance_matches_bs_status.value
                    if statement_balance_matches_bs_status is not None
                    else None,
                    "require_statement_balance_matches_attachment": True,
                    "statement_balance_attachment_evidence_type": cfg.statement_balance_attachment_evidence_type,
                    "attachment_statement_end_date": attachment_statement_end_date.isoformat()
                    if attachment_statement_end_date is not None
                    else None,
                    "attachment_amount": str(attachment_amount) if attachment_amount is not None else None,
                    "attachment_uri": attachment_uri,
                    "attachment_balance_difference": str(attachment_diff) if attachment_diff is not None else None,
                    "attachment_status": attachment_status.value if attachment_status is not None else None,
                    "status": status.value,
                },
            ),
        )

    def _is_bank_or_credit_card(self, acct: AccountBalance) -> bool:
        """Decide whether a Balance Sheet account should be included in bank/cc scope (type/subtype only)."""
        type_l = (acct.type or "").strip().lower()
        subtype_l = (acct.subtype or "").strip().lower()
        if not (type_l or subtype_l):
            return False
        if "bank" in type_l or "bank" in subtype_l:
            return True
        if "credit" in type_l or "credit" in subtype_l:
            return True
        if "card" in type_l or "card" in subtype_l:
            return True
        return False

    def _infer_scope_from_balance_sheet(
        self, ctx: RuleContext
    ) -> tuple[list[str] | None, RuleResultDetail | None]:
        # Default: infer scope from Balance Sheet account type/subtype; if any types are missing, flag for review.
        missing_type_refs: list[str] = []
        inferred: list[str] = []
        for acct in ctx.balance_sheet.accounts:
            if not ((acct.type or "").strip() or (acct.subtype or "").strip()):
                missing_type_refs.append(acct.account_ref)
                continue
            if self._is_bank_or_credit_card(acct):
                inferred.append(acct.account_ref)

        if missing_type_refs:
            return None, RuleResultDetail(
                key="scope",
                message="Cannot infer bank/cc scope because some Balance Sheet accounts are missing type/subtype.",
                values={
                    "period_end": ctx.period_end.isoformat(),
                    "missing_type_account_refs": missing_type_refs[:20],
                    "missing_type_account_count": len(missing_type_refs),
                    "status": RuleStatus.NEEDS_REVIEW.value,
                },
            )

        return sorted(inferred), None

    def _determine_scope(
        self,
        ctx: RuleContext,
        cfg: BankReconciledThroughPeriodEndRuleConfig,
        inferred_refs: list[str],
    ) -> list[str]:
        exclude = list(cfg.exclude_accounts or [])

        # Back-compat: if `expected_accounts[]` is provided, treat it as the explicit scope list.
        if cfg.expected_accounts:
            return sorted([r for r in cfg.expected_accounts if r not in set(exclude)])

        refs = sorted((set(inferred_refs) | set(cfg.include_accounts or [])) - set(exclude))
        return refs

    def _check_maintenance_count(
        self,
        ctx: RuleContext,
        cfg: BankReconciledThroughPeriodEndRuleConfig,
        inferred_refs: list[str] | None,
    ) -> tuple[RuleStatus | None, RuleResultDetail | None]:
        """
        Compare maintenance list count to inferred bank/cc accounts from the Balance Sheet.
        """
        if not cfg.expected_accounts:
            return None, None

        if inferred_refs is None:
            return (
                RuleStatus.NEEDS_REVIEW,
                RuleResultDetail(
                    key="scope_count",
                    message="Cannot compare maintenance list to Balance Sheet bank/cc count (missing type/subtype).",
                    values={
                        "period_end": ctx.period_end.isoformat(),
                        "maintenance_account_count": len(cfg.expected_accounts),
                        "status": RuleStatus.NEEDS_REVIEW.value,
                    },
                ),
            )

        maintenance_refs = list(cfg.expected_accounts)
        inferred_set = set(inferred_refs)
        maintenance_set = set(maintenance_refs)

        missing_in_bs = sorted(maintenance_set - inferred_set)
        extra_in_bs = sorted(inferred_set - maintenance_set)

        if len(maintenance_refs) != len(inferred_refs):
            return (
                RuleStatus.FAIL,
                RuleResultDetail(
                    key="scope_count",
                    message="Maintenance bank/cc account count does not match Balance Sheet bank/cc count.",
                    values={
                        "period_end": ctx.period_end.isoformat(),
                        "maintenance_account_count": len(maintenance_refs),
                        "balance_sheet_bank_cc_count": len(inferred_refs),
                        "missing_in_balance_sheet": missing_in_bs[:20],
                        "extra_in_balance_sheet": extra_in_bs[:20],
                        "status": RuleStatus.FAIL.value,
                    },
                ),
            )

        return (
            RuleStatus.PASS,
            RuleResultDetail(
                key="scope_count",
                message="Maintenance bank/cc account count matches Balance Sheet bank/cc count.",
                values={
                    "period_end": ctx.period_end.isoformat(),
                    "maintenance_account_count": len(maintenance_refs),
                    "balance_sheet_bank_cc_count": len(inferred_refs),
                    "status": RuleStatus.PASS.value,
                },
            ),
        )
