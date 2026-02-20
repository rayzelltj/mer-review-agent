from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from adapters.qbo.bank_cc_reconciliation import (
    active_bank_cc_accounts_from_accounts_payload,
    coerce_report_payload,
    transaction_list_unreconciled_sums_from_report,
    trial_balance_register_balances_from_report,
)

from ..config import BankReconciledThroughPeriodEndRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, StatusOrdering, severity_for_status
from ..registry import register_rule
from ..rule import Rule

BANK_NAME_HINTS = ("chequing", "checking", "savings", "bank", "rbc", "td", "bmo", "cibc", "scotia")
CC_NAME_HINTS = ("visa", "mastercard", "master card", "amex", "credit card", " cc ")


def _as_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _canonical_account_id(account_ref: str) -> str:
    raw = str(account_ref or "").strip()
    if not raw:
        return ""
    return raw.split("::")[-1]


def _matches_account(meta: dict[str, Any], *, account_ref: str, account_id: str) -> bool:
    ref = str(meta.get("account_ref") or "").strip()
    acc_id = str(meta.get("account_id") or "").strip()
    if ref and (ref == account_ref or _canonical_account_id(ref) == account_id):
        return True
    if acc_id and acc_id == account_id:
        return True
    return False


def _statement_sign_normalized(account_type: str, amount: Decimal) -> Decimal:
    # Statement ending balance is always expressed as an absolute "you-owe" (CC) or
    # "you-have" (Bank) amount from the statement perspective.  No sign flip needed
    # because the CC register balance is independently normalised to the same
    # positive "you-owe" convention in the evaluate() loop below.
    return amount


@register_rule
class BS_BANK_RECONCILED_THROUGH_PERIOD_END(Rule):
    rule_id = "BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END"
    rule_title = "Bank/credit card accounts reconcile using statement, trial balance, and unreconciled transactions"
    best_practices_reference = "Bank reconciliations -> Banks and credit cards"
    sources = [
        "QBO (Chart of Accounts, Trial Balance, Transaction List by Account)",
        "Bank statements/activity statements (evidence)",
    ]
    config_model = BankReconciledThroughPeriodEndRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, BankReconciledThroughPeriodEndRuleConfig)
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

        coa_accounts, scope_source = self._bank_cc_scope_from_coa(ctx, cfg)
        if not coa_accounts:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary=(
                    "No active bank/credit-card scope could be built from Chart of Accounts evidence; "
                    "cannot evaluate reconciliation."
                ),
                details=[
                    RuleResultDetail(
                        key="scope",
                        message="Missing CoA bank/credit-card scope evidence.",
                        values={
                            "period_end": ctx.period_end.isoformat(),
                            "chart_of_accounts_evidence_type": cfg.chart_of_accounts_evidence_type,
                            "allow_fallback_name_heuristics_when_coa_missing": cfg.allow_fallback_name_heuristics_when_coa_missing,
                            "status": missing_status.value,
                        },
                    )
                ],
                human_action=(
                    "Provide Chart of Accounts evidence with active Bank/Credit Card accounts "
                    f"({cfg.chart_of_accounts_evidence_type})."
                ),
            )

        refs = self._determine_scope(cfg, [row["account_ref"] for row in coa_accounts])
        if not refs:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No in-scope bank/credit-card accounts as of {ctx.period_end.isoformat()}.",
            )

        coa_by_ref = {row["account_ref"]: row for row in coa_accounts}
        coa_by_id = {_canonical_account_id(row["account_ref"]): row for row in coa_accounts}
        bs_name_by_ref = {row.account_ref: row.name for row in ctx.balance_sheet.accounts}
        bs_balance_by_ref = {row.account_ref: row.balance for row in ctx.balance_sheet.accounts}
        bs_balance_by_id = {
            _canonical_account_id(row.account_ref): row.balance
            for row in ctx.balance_sheet.accounts
        }
        trial_balances = self._trial_balance_map(ctx, cfg)
        tx_items = [item for item in ctx.evidence.items if item.evidence_type == cfg.transaction_list_evidence_type]
        statement_items = [
            item for item in ctx.evidence.items if item.evidence_type == cfg.statement_balance_attachment_evidence_type
        ]

        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []
        ordering = StatusOrdering.default()

        for account_ref in refs:
            account_id = _canonical_account_id(account_ref)
            coa_row = coa_by_ref.get(account_ref) or coa_by_id.get(account_id) or {}
            account_name = str(coa_row.get("account_name") or bs_name_by_ref.get(account_ref) or account_ref)
            account_type = str(coa_row.get("account_type") or "")
            account_active = bool(coa_row.get("active", True))

            statement_item = self._find_best_statement_item(
                statement_items,
                account_ref=account_ref,
                account_id=account_id,
            )
            statement_balance = None
            statement_end_date = ctx.period_end
            statement_balance_source = None
            if statement_item is not None:
                statement_end_date = (
                    statement_item.statement_end_date
                    or statement_item.as_of_date
                    or ctx.period_end
                )
                if statement_item.amount is not None:
                    statement_balance = statement_item.amount
                    statement_balance_source = "evidence.amount"
                else:
                    statement_balance = self._statement_amount_from_meta(statement_item.meta or {})
                    statement_balance_source = "evidence.meta"
            register_balance = trial_balances.get(account_ref)
            if register_balance is None:
                register_balance = trial_balances.get(account_id)

            # For Credit Card accounts the trial-balance net is debit − credit,
            # which is a *negative* number when the card has an outstanding balance
            # (the normal case).  Negate it so the register balance is expressed as
            # the positive "amount owed to the card issuer" — the same perspective
            # used by the bank statement.  This makes the equation:
            #   expected_outstanding = register_balance − statement_ending_balance
            # produce a positive result that S1 (sum of positive unreconciled charges)
            # can be directly compared against.
            if account_type == "Credit Card" and register_balance is not None and register_balance < 0:
                register_balance = -register_balance

            # Rule 2: look up the matching balance-sheet line for this account.
            bs_balance = bs_balance_by_ref.get(account_ref)
            if bs_balance is None:
                bs_balance = bs_balance_by_id.get(account_id)

            tx_summary = self._transaction_summary(
                tx_items,
                account_ref=account_ref,
                account_id=account_id,
                period_end=ctx.period_end,
                statement_end_date=statement_end_date,
            )
            s1 = tx_summary.get("sum_not_reconciled_as_of_period_end")
            s2 = tx_summary.get("sum_not_reconciled_between_period_end_and_statement_end")
            clear_column_found = bool(tx_summary.get("clear_status_column_found"))

            missing_fields: list[str] = []
            if statement_balance is None:
                missing_fields.append("statement_ending_balance")
            if register_balance is None:
                missing_fields.append("trial_balance_register_balance")
            if s1 is None or s2 is None:
                missing_fields.append("transaction_list_s1_s2")
            if not clear_column_found:
                missing_fields.append("transaction_list_clear_status_column")

            if missing_fields:
                status = missing_status
                detail = RuleResultDetail(
                    key=account_ref,
                    message="Missing data required for bank/credit-card reconciliation equation.",
                    values={
                        "account_name": account_name,
                        "account_ref": account_ref,
                        "account_id": account_id,
                        "account_type": account_type,
                        "account_active": account_active,
                        "scope_source": scope_source,
                        "period_end": ctx.period_end.isoformat(),
                        "statement_end_date": statement_end_date.isoformat() if statement_end_date else None,
                        "statement_balance_attachment_evidence_type": cfg.statement_balance_attachment_evidence_type,
                        "trial_balance_evidence_type": cfg.trial_balance_evidence_type,
                        "transaction_list_evidence_type": cfg.transaction_list_evidence_type,
                        "statement_balance": str(statement_balance) if statement_balance is not None else None,
                        "register_balance": str(register_balance) if register_balance is not None else None,
                        "s1_not_reconciled_as_of_period_end": str(s1) if s1 is not None else None,
                        "s2_not_reconciled_between_period_end_and_statement_end": str(s2) if s2 is not None else None,
                        "bs_line_balance": str(bs_balance) if bs_balance is not None else None,
                        "missing_fields": missing_fields,
                        "status": status.value,
                    },
                )
                statuses.append(status)
                details.append(detail)
                continue

            statement_balance = _statement_sign_normalized(account_type, statement_balance)
            register_q = quantize_amount(register_balance, cfg.amount_quantize)
            statement_q = quantize_amount(statement_balance, cfg.amount_quantize)
            s1_q = quantize_amount(s1, cfg.amount_quantize)
            s2_q = quantize_amount(s2, cfg.amount_quantize)

            expected = quantize_amount(register_q - statement_q, cfg.amount_quantize)
            diff_expected_minus_s1 = quantize_amount(expected - s1_q, cfg.amount_quantize)
            pass_s1 = diff_expected_minus_s1 == 0
            pass_s2 = diff_expected_minus_s1 == s2_q

            if pass_s1 or pass_s2:
                status = RuleStatus.PASS
                equation_result = "PASS"
            else:
                status = RuleStatus.WARN
                equation_result = "MISMATCH_REVIEW"

            # Sub-check Rule 2: trial-balance register balance must match the
            # balance-sheet line for the same account.  A mismatch means the two
            # data sources are inconsistent and deserves a WARN even when the
            # reconciliation equation itself passes.
            bs_line_balance: str | None = None
            register_matches_bs_line: bool | None = None
            bs_vs_register_diff: str | None = None
            if bs_balance is not None:
                _reg_abs = abs(register_q)
                _bs_abs = abs(quantize_amount(bs_balance, cfg.amount_quantize))
                _diff_bs = abs(_reg_abs - _bs_abs)
                register_matches_bs_line = _diff_bs <= Decimal("0.02")
                bs_line_balance = str(_bs_abs)
                bs_vs_register_diff = str(_diff_bs)
                if not register_matches_bs_line and status == RuleStatus.PASS:
                    status = RuleStatus.WARN
                    equation_result = "PASS_BUT_REGISTER_VS_BS_MISMATCH"

            statuses.append(status)
            details.append(
                RuleResultDetail(
                    key=account_ref,
                    message="Bank/credit-card equation evaluated.",
                    values={
                        "account_name": account_name,
                        "account_ref": account_ref,
                        "account_id": account_id,
                        "account_type": account_type,
                        "account_active": account_active,
                        "scope_source": scope_source,
                        "period_end": ctx.period_end.isoformat(),
                        "statement_end_date": statement_end_date.isoformat() if statement_end_date else None,
                        "statement_balance_source": statement_balance_source,
                        "statement_balance": str(statement_q),
                        "register_balance": str(register_q),
                        "equation_1": "expected_outstanding = register_balance - statement_ending_balance  [CC: register_balance = abs(trial_balance_net)]",
                        "expected_outstanding": str(expected),
                        "equation_2": "S1 = sum(unreconciled as of period end: blank + C, positive amounts for charges)",
                        "s1_not_reconciled_as_of_period_end": str(s1_q),
                        "equation_3": "S2 = sum(unreconciled between period end and reconciliation date)",
                        "s2_not_reconciled_between_period_end_and_statement_end": str(s2_q),
                        "expected_minus_s1": str(diff_expected_minus_s1),
                        "pass_if_expected_equals_s1": pass_s1,
                        "pass_if_expected_minus_s1_equals_s2": pass_s2,
                        "transaction_list_parsed_rows": tx_summary.get("parsed_rows"),
                        "transaction_list_ignored_rows": tx_summary.get("ignored_rows"),
                        "clear_status_column_found": clear_column_found,
                        "active_account_filter_applied": cfg.require_active_accounts_only,
                        "bs_line_balance": bs_line_balance,
                        "register_matches_bs_line": register_matches_bs_line,
                        "bs_vs_register_diff": bs_vs_register_diff,
                        "sub_check_register_vs_bs": (
                            "PASS" if register_matches_bs_line is True
                            else "WARN" if register_matches_bs_line is False
                            else None
                        ),
                        "status": status.value,
                        "equation_result": equation_result,
                    },
                )
            )

        overall = ordering.worst(statuses)
        severity = severity_for_status(overall)
        exemplar = next((d for d in details if d.values.get("status") == overall.value), None)

        if overall == RuleStatus.PASS:
            summary = (
                f"All {len(refs)} active bank/credit-card account(s) passed reconciliation equation "
                f"as of {ctx.period_end.isoformat()}."
            )
        elif overall == RuleStatus.WARN and exemplar:
            summary = (
                f"Equation mismatch for '{exemplar.values.get('account_name','')}' as of {ctx.period_end.isoformat()} "
                "(review expected outstanding vs S1/S2)."
            )
        elif overall == RuleStatus.NEEDS_REVIEW:
            summary = (
                f"Missing evidence prevented full bank/credit-card reconciliation equation evaluation "
                f"as of {ctx.period_end.isoformat()}."
            )
        else:
            summary = "Not applicable."

        human_action = None
        if overall in (RuleStatus.WARN, RuleStatus.NEEDS_REVIEW):
            human_action = (
                "Provide/verify: active CoA bank/credit-card scope, statement ending balances per account, "
                "trial balance register balances at month end, and transaction-list unreconciled sums (S1/S2)."
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

    def _bank_cc_scope_from_coa(
        self,
        ctx: RuleContext,
        cfg: BankReconciledThroughPeriodEndRuleConfig,
    ) -> tuple[list[dict[str, Any]], str]:
        scoped: list[dict[str, Any]] = []
        for item in ctx.evidence.items:
            if item.evidence_type != cfg.chart_of_accounts_evidence_type:
                continue
            rows = item.meta.get("accounts")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                account_ref = str(row.get("account_ref") or "").strip()
                account_type = str(row.get("account_type") or "").strip()
                if not account_ref or account_type not in {"Bank", "Credit Card"}:
                    continue
                if cfg.require_active_accounts_only and row.get("active") is False:
                    continue
                scoped.append(row)

        if scoped:
            return sorted(scoped, key=lambda row: row["account_ref"]), "chart_of_accounts"

        if not cfg.allow_fallback_name_heuristics_when_coa_missing:
            return [], "chart_of_accounts_missing"

        fallback: list[dict[str, Any]] = []
        seen: set[str] = set()
        for acct in ctx.balance_sheet.accounts:
            ref = acct.account_ref
            if not ref or ref in seen:
                continue
            type_l = (acct.type or "").strip().lower()
            subtype_l = (acct.subtype or "").strip().lower()
            name_l = f" {((acct.name or '').strip().lower())} "
            is_bank_cc = any(token in type_l for token in ("bank", "credit", "card")) or any(
                token in subtype_l for token in ("bank", "credit", "card")
            )
            if not is_bank_cc:
                bank_hint = any(token in name_l for token in BANK_NAME_HINTS)
                cc_hint = any(token in name_l for token in CC_NAME_HINTS)
                is_bank_cc = bank_hint or cc_hint
            if not is_bank_cc:
                continue
            seen.add(ref)
            fallback.append(
                {
                    "account_ref": ref,
                    "account_id": _canonical_account_id(ref),
                    "account_name": acct.name,
                    "account_type": "Credit Card"
                    if any(token in name_l for token in CC_NAME_HINTS)
                    else "Bank",
                    "active": True,
                    "inferred_by_name_heuristic": True,
                }
            )
        return sorted(fallback, key=lambda row: row["account_ref"]), "fallback_heuristic"

    def _determine_scope(
        self,
        cfg: BankReconciledThroughPeriodEndRuleConfig,
        inferred_refs: list[str],
    ) -> list[str]:
        exclude = set(cfg.exclude_accounts or [])
        if cfg.expected_accounts:
            return sorted([ref for ref in cfg.expected_accounts if ref not in exclude])
        refs = (set(inferred_refs) | set(cfg.include_accounts or [])) - exclude
        return sorted(refs)

    def _trial_balance_map(
        self,
        ctx: RuleContext,
        cfg: BankReconciledThroughPeriodEndRuleConfig,
    ) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for item in ctx.evidence.items:
            if item.evidence_type != cfg.trial_balance_evidence_type:
                continue
            direct = item.meta.get("balances_by_account_ref")
            if isinstance(direct, dict):
                for key, value in direct.items():
                    amount = _as_decimal(value)
                    if amount is None:
                        continue
                    out[str(key)] = amount
            report_payload = item.meta.get("report")
            report = coerce_report_payload(report_payload) if report_payload is not None else None
            if report is None:
                report = coerce_report_payload(item.meta)
            if report is not None:
                out.update(trial_balance_register_balances_from_report(report))
        return out

    def _find_best_statement_item(
        self,
        items: list[Any],
        *,
        account_ref: str,
        account_id: str,
    ):
        candidates = [
            item
            for item in items
            if _matches_account(item.meta or {}, account_ref=account_ref, account_id=account_id)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: item.statement_end_date or item.as_of_date or date.min,
        )

    def _statement_amount_from_meta(self, meta: dict[str, Any]) -> Decimal | None:
        for key in ("ending_balance", "statement_ending_balance", "available_ending", "amount"):
            value = _as_decimal(meta.get(key))
            if value is not None:
                return value
        return None

    def _transaction_summary(
        self,
        tx_items: list[Any],
        *,
        account_ref: str,
        account_id: str,
        period_end: date,
        statement_end_date: date,
    ) -> dict[str, Any]:
        for item in tx_items:
            meta = item.meta or {}
            if not _matches_account(meta, account_ref=account_ref, account_id=account_id):
                continue
            s1 = _as_decimal(meta.get("sum_not_reconciled_as_of_period_end"))
            s2 = _as_decimal(meta.get("sum_not_reconciled_between_period_end_and_statement_end"))
            if s1 is not None and s2 is not None:
                return {
                    "sum_not_reconciled_as_of_period_end": s1,
                    "sum_not_reconciled_between_period_end_and_statement_end": s2,
                    "clear_status_column_found": bool(meta.get("clear_status_column_found", True)),
                    "parsed_rows": meta.get("parsed_rows"),
                    "ignored_rows": meta.get("ignored_rows"),
                }
            report = meta.get("report")
            if report is None and isinstance(meta.get("payload"), dict):
                report = meta.get("payload")
            if report is not None:
                parsed = transaction_list_unreconciled_sums_from_report(
                    report,
                    period_end=period_end,
                    statement_end_date=statement_end_date,
                )
                return parsed
        return {
            "sum_not_reconciled_as_of_period_end": None,
            "sum_not_reconciled_between_period_end_and_statement_end": None,
            "clear_status_column_found": False,
            "parsed_rows": 0,
            "ignored_rows": 0,
        }
