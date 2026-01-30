from __future__ import annotations

from decimal import Decimal

from ..config import ApSubledgerReconcilesRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_AP_SUBLEDGER_RECONCILES(Rule):
    rule_id = "BS-AP-SUBLEDGER-RECONCILES"
    rule_title = "Aged Payables Detail reconciles to Balance Sheet"
    best_practices_reference = "Accounts Payable/Receivable"
    sources = ["QBO"]
    config_model = ApSubledgerReconcilesRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, ApSubledgerReconcilesRuleConfig)
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

        accounts_to_eval: list[tuple[str, str, Decimal]] = []
        used_name_inference = False
        used_total_line = False
        missing_refs: list[str] = []

        total_matches = [
            acct
            for acct in ctx.balance_sheet.accounts
            if self._is_total_ap(acct.name or "")
        ]
        if len(total_matches) > 1:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Multiple AP total lines found in Balance Sheet as of {ctx.period_end.isoformat()}; "
                    "cannot verify."
                ),
                details=[
                    RuleResultDetail(
                        key=acct.account_ref,
                        message="Multiple AP total lines matched.",
                        values={
                            "account_name": acct.name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": RuleStatus.NEEDS_REVIEW.value,
                        },
                    )
                    for acct in total_matches
                ],
                human_action="Use a single AP total line or configure specific account refs.",
            )
        if total_matches:
            acct = total_matches[0]
            accounts_to_eval = [(acct.account_ref, acct.name, acct.balance)]
            used_total_line = True
        elif cfg.account_refs:
            for ref in cfg.account_refs:
                bal = ctx.get_account_balance(ref)
                if bal is None:
                    missing_refs.append(ref)
                    continue
                acct_name = next(
                    (acct.name for acct in ctx.balance_sheet.accounts if acct.account_ref == ref), ""
                )
                accounts_to_eval.append((ref, acct_name, bal))
        elif cfg.allow_name_inference:
            used_name_inference = True
            name_match = (cfg.account_name_match or "").lower()
            for acct in ctx.balance_sheet.accounts:
                acct_name = (acct.name or "").lower()
                if name_match and name_match in acct_name:
                    accounts_to_eval.append((acct.account_ref, acct.name, acct.balance))
                    continue
                if "a/p" in acct_name:
                    accounts_to_eval.append((acct.account_ref, acct.name, acct.balance))

        if not accounts_to_eval:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No Accounts Payable accounts found as of {ctx.period_end.isoformat()}.",
                human_action="Configure AP account refs or name match to enable this rule.",
            )

        if missing_refs:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Some configured AP accounts were missing from the Balance Sheet as of "
                    f"{ctx.period_end.isoformat()}; cannot verify."
                ),
                details=[
                    RuleResultDetail(
                        key=ref,
                        message="Configured account not found in balance sheet snapshot.",
                        values={
                            "period_end": ctx.period_end.isoformat(),
                            "status": RuleStatus.NEEDS_REVIEW.value,
                        },
                    )
                    for ref in missing_refs
                ],
                human_action="Confirm AP account refs and ensure the Balance Sheet snapshot is complete.",
            )

        summary_item = ctx.evidence.first(cfg.summary_evidence_type)
        detail_item = ctx.evidence.first(cfg.detail_evidence_type)
        if summary_item is None or summary_item.amount is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Missing AP aging summary total for {ctx.period_end.isoformat()}; cannot verify."
                ),
                evidence_used=[summary_item] if summary_item else [],
                human_action="Provide the AP aging summary total as of period end.",
            )
        if detail_item is None or detail_item.amount is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                summary=(
                    f"Missing AP aging detail total for {ctx.period_end.isoformat()}; cannot verify."
                ),
                evidence_used=[detail_item] if detail_item else [],
                human_action="Provide the AP aging detail total as of period end.",
            )

        if cfg.require_evidence_as_of_date_match_period_end:
            if summary_item.as_of_date is None or summary_item.as_of_date != ctx.period_end:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=RuleStatus.NEEDS_REVIEW,
                    severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                    summary=(
                        "AP aging summary as-of date is missing or does not match period end; cannot verify."
                    ),
                    evidence_used=[summary_item],
                    human_action="Provide the AP aging summary as of the period end date.",
                )
            if detail_item.as_of_date is None or detail_item.as_of_date != ctx.period_end:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=RuleStatus.NEEDS_REVIEW,
                    severity=severity_for_status(RuleStatus.NEEDS_REVIEW),
                    summary=(
                        "AP aging detail as-of date is missing or does not match period end; cannot verify."
                    ),
                    evidence_used=[detail_item],
                    human_action="Provide the AP aging detail report as of the period end date.",
                )

        bs_total = sum((bal for _, _, bal in accounts_to_eval), Decimal("0"))
        bs_q = quantize_amount(bs_total, cfg.amount_quantize)
        summary_q = quantize_amount(summary_item.amount, cfg.amount_quantize)
        detail_q = quantize_amount(detail_item.amount, cfg.amount_quantize)

        diff_summary = abs(bs_q - summary_q)
        diff_detail = abs(bs_q - detail_q)

        if diff_summary == 0 and diff_detail == 0:
            status = RuleStatus.PASS
            severity = severity_for_status(status)
            summary = f"AP aging totals reconcile to the Balance Sheet as of {ctx.period_end.isoformat()}."
        else:
            status = RuleStatus.FAIL
            severity = severity_for_status(status)
            summary = (
                f"AP aging totals do not reconcile to the Balance Sheet as of {ctx.period_end.isoformat()}."
            )

        human_action = None
        if status != RuleStatus.PASS:
            human_action = (
                "Reconcile the AP aging summary/detail totals to the Balance Sheet and resolve discrepancies."
            )

        details = [
            RuleResultDetail(
                key=ref,
                message="AP account included in Balance Sheet total.",
                values={
                    "account_name": name,
                    "period_end": ctx.period_end.isoformat(),
                    "balance": str(quantize_amount(bal, cfg.amount_quantize)),
                    "inferred_by_name_match": used_name_inference,
                    "used_total_line": used_total_line,
                },
            )
            for ref, name, bal in accounts_to_eval
        ]
        details.append(
            RuleResultDetail(
                key="ap_aging_totals",
                message="AP aging totals compared to Balance Sheet total.",
                values={
                    "period_end": ctx.period_end.isoformat(),
                    "bs_total": str(bs_q),
                    "summary_total": str(summary_q),
                    "detail_total": str(detail_q),
                    "summary_difference": str(diff_summary),
                    "detail_difference": str(diff_detail),
                    "summary_evidence_type": cfg.summary_evidence_type,
                    "detail_evidence_type": cfg.detail_evidence_type,
                    "summary_evidence_as_of_date": summary_item.as_of_date.isoformat()
                    if summary_item.as_of_date is not None
                    else None,
                    "detail_evidence_as_of_date": detail_item.as_of_date.isoformat()
                    if detail_item.as_of_date is not None
                    else None,
                    "status": status.value,
                },
            )
        )

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=status,
            severity=severity,
            summary=summary,
            details=details,
            evidence_used=[summary_item, detail_item],
            human_action=human_action,
        )

    def _is_total_ap(self, name: str) -> bool:
        n = name.strip().lower()
        if "total" not in n:
            return False
        if "accounts payable" in n:
            return True
        if "a/p" in n:
            return True
        return False
