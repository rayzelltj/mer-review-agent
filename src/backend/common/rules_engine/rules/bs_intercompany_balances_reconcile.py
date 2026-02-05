from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import IntercompanyBalancesReconcileRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if not s:
            return None
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


@register_rule
class BS_INTERCOMPANY_BALANCES_RECONCILE(Rule):
    rule_id = "BS-INTERCOMPANY-BALANCES-RECONCILE"
    rule_title = "Intercompany loan balances reconcile across related companies"
    best_practices_reference = "Intercompany Loans"
    sources = ["QBO (Balance Sheet)", "Counterparty Balance Sheets"]
    config_model = IntercompanyBalancesReconcileRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, IntercompanyBalancesReconcileRuleConfig)
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

        patterns = [p.strip().lower() for p in (cfg.name_patterns or []) if str(p).strip()]
        intercompany_loans = []
        for acct in ctx.balance_sheet.accounts:
            name = (acct.name or "").lower()
            if not any(p in name for p in patterns):
                continue
            bal = _parse_decimal(acct.balance)
            if bal is None:
                continue
            if cfg.non_zero_only and bal == 0:
                continue
            intercompany_loans.append(
                {
                    "account_ref": acct.account_ref,
                    "account_name": acct.name,
                    "balance": bal,
                }
            )

        if not intercompany_loans:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No intercompany loan balances found as of {ctx.period_end.isoformat()}.",
            )

        evidence_item = ctx.evidence.first(cfg.evidence_type)
        if evidence_item is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary=(
                    f"Intercompany loan balances detected but no counterpart Balance Sheet evidence provided "
                    f"for {ctx.period_end.isoformat()}."
                ),
                human_action="Provide counterpart Balance Sheet evidence for intercompany loan balances.",
            )
        if cfg.require_evidence_as_of_date_match_period_end:
            if evidence_item.as_of_date is None or evidence_item.as_of_date != ctx.period_end:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=missing_status,
                    severity=severity_for_status(missing_status),
                    summary=(
                        "Counterpart Balance Sheet evidence date missing or does not match period end; "
                        "cannot verify."
                    ),
                    evidence_used=[evidence_item],
                    human_action="Provide counterpart Balance Sheets as of period end.",
                )

        counterpart_items = evidence_item.meta.get("items") if isinstance(evidence_item.meta, dict) else None
        if not isinstance(counterpart_items, list):
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Counterpart Balance Sheet evidence missing items; cannot verify.",
                evidence_used=[evidence_item],
                human_action="Provide intercompany loan balances from counterpart Balance Sheets.",
            )

        counterpart_map: dict[str, Decimal] = {}
        for item in counterpart_items:
            if not isinstance(item, dict):
                continue
            counterparty = str(item.get("counterparty") or item.get("company") or "").strip()
            amt = _parse_decimal(item.get("balance"))
            if not counterparty or amt is None:
                continue
            counterpart_map[counterparty.lower()] = amt

        mismatches = []
        details = []
        for acct in intercompany_loans:
            name = acct["account_name"]
            bal = quantize_amount(acct["balance"], cfg.amount_quantize)
            counterparty = self._extract_counterparty(name, patterns)
            cp_balance = counterpart_map.get((counterparty or "").lower())
            if cp_balance is None:
                mismatches.append(
                    {
                        "account_name": name,
                        "balance": str(bal),
                        "counterparty": counterparty,
                        "counterparty_balance": None,
                        "reason": "missing_counterparty_balance",
                    }
                )
            else:
                cp_q = quantize_amount(cp_balance, cfg.amount_quantize)
                if abs(bal) != abs(cp_q):
                    mismatches.append(
                        {
                            "account_name": name,
                            "balance": str(bal),
                            "counterparty": counterparty,
                            "counterparty_balance": str(cp_q),
                            "reason": "amount_mismatch",
                        }
                    )
            detail_status = RuleStatus.NEEDS_REVIEW.value if any(
                m.get("account_name") == name for m in mismatches
            ) else RuleStatus.PASS.value
            details.append(
                RuleResultDetail(
                    key=acct["account_ref"],
                    message="Intercompany loan balance evaluated.",
                    values={
                        "account_name": name,
                        "period_end": ctx.period_end.isoformat(),
                        "balance": str(bal),
                        "counterparty": counterparty,
                        "counterparty_balance": str(cp_balance) if cp_balance is not None else None,
                        "status": detail_status,
                    },
                )
            )

        status = RuleStatus.NEEDS_REVIEW if mismatches else RuleStatus.PASS
        summary = (
            "Intercompany loan balances require review (missing or mismatched counterpart balances)."
            if mismatches
            else f"Intercompany loan balances match counterpart Balance Sheets as of {ctx.period_end.isoformat()}."
        )
        human_action = (
            "Confirm counterpart balances and reconcile intercompany loan accounts."
            if mismatches
            else None
        )

        details.append(
            RuleResultDetail(
                key="intercompany_loan_summary",
                message="Intercompany loan comparison summary.",
                values={
                    "period_end": ctx.period_end.isoformat(),
                    "mismatch_count": len(mismatches),
                    "mismatches": mismatches[:25],
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
            severity=severity_for_status(status),
            summary=summary,
            details=details,
            evidence_used=[evidence_item],
            human_action=human_action,
        )

    def _extract_counterparty(self, name: str, patterns: list[str]) -> str:
        lower = name.lower()
        for p in patterns:
            idx = lower.find(p)
            if idx != -1:
                candidate = name[idx + len(p) :].strip()
                if candidate:
                    return candidate
        return name
