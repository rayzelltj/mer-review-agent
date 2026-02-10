from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import ApArIntercompanyOrShareholderPaidRuleConfig
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


AP_AR_DIRECTION_KEYWORDS = [
    ("due from", "due_from"),
    ("due to", "due_to"),
    ("intercompany", "intercompany"),
    ("inter-company", "intercompany"),
]

AP_AR_DIRECTION_MAP = {
    "due_from": "due_to",
    "due_to": "due_from",
    "intercompany": "intercompany",
}


def _expected_counterparty_direction(
    direction: str | None,
    mapping: dict[str, str],
) -> str | None:
    if direction is None:
        return None
    return mapping.get(direction)


def _extract_counterparty(name: str, patterns: list[str]) -> str:
    lower = name.lower()
    for p in patterns:
        idx = lower.find(p)
        if idx != -1:
            candidate = name[idx + len(p) :].strip()
            if candidate:
                return candidate
    return name


def _classify_direction(
    name: str,
    patterns: list[str],
    keywords: list[tuple[str, str]],
) -> tuple[str | None, str]:
    lower = name.lower()
    for token, kind in keywords:
        idx = lower.find(token)
        if idx != -1:
            candidate = name[idx + len(token) :].strip()
            return kind, candidate or name
    return None, _extract_counterparty(name, patterns)


@register_rule
class BS_AP_AR_INTERCOMPANY_OR_SHAREHOLDER_PAID(Rule):
    rule_id = "BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID"
    rule_title = "Intercompany/shareholder-paid balances identified"
    best_practices_reference = "Accounts Payable/Receivable"
    sources = ["QBO (Balance Sheet)"]
    config_model = ApArIntercompanyOrShareholderPaidRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, ApArIntercompanyOrShareholderPaidRuleConfig)
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
        intercompany_accounts = []
        for acct in ctx.balance_sheet.accounts:
            name = (acct.name or "").lower()
            if not any(p in name for p in patterns):
                continue
            bal = _parse_decimal(acct.balance)
            if bal is None:
                continue
            if cfg.non_zero_only and bal == 0:
                continue
            intercompany_accounts.append(
                {
                    "account_ref": acct.account_ref,
                    "account_name": acct.name,
                    "balance": bal,
                }
            )

        if not intercompany_accounts:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No intercompany balances found as of {ctx.period_end.isoformat()}.",
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
                    f"Intercompany accounts detected but no counterpart Balance Sheet evidence provided "
                    f"for {ctx.period_end.isoformat()}."
                ),
                human_action="Provide counterpart company Balance Sheet evidence for intercompany balances.",
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
                human_action="Provide intercompany balances from counterpart Balance Sheets.",
            )

        counterpart_balances: dict[tuple[str, str], Decimal] = {}
        counterparty_kinds: dict[str, set[str]] = {}
        for item in counterpart_items:
            if not isinstance(item, dict):
                continue
            account_name = str(item.get("account_name") or "").strip()
            kind, extracted_cp = (
                _classify_direction(account_name, patterns, AP_AR_DIRECTION_KEYWORDS)
                if account_name
                else (None, "")
            )
            counterparty = str(
                item.get("company") or item.get("entity") or item.get("counterparty") or ""
            ).strip()
            if not counterparty:
                counterparty = extracted_cp
            amt = _parse_decimal(item.get("balance"))
            if not counterparty or amt is None:
                continue
            if kind is None:
                counterparty_kinds.setdefault(counterparty.lower(), set()).add("unknown")
                continue
            counterpart_balances[(counterparty.lower(), kind)] = amt
            counterparty_kinds.setdefault(counterparty.lower(), set()).add(kind)

        mismatches = []
        details = []
        for acct in intercompany_accounts:
            name = acct["account_name"]
            bal = quantize_amount(acct["balance"], cfg.amount_quantize)
            direction, counterparty = _classify_direction(
                name, patterns, AP_AR_DIRECTION_KEYWORDS
            )
            expected_direction = _expected_counterparty_direction(
                direction, AP_AR_DIRECTION_MAP
            )
            counterparty_key = (counterparty or "").lower()
            cp_balance = None
            mismatch_reason = None
            found_direction = None
            if expected_direction is None:
                mismatch_reason = "direction_unknown"
            else:
                cp_balance = counterpart_balances.get(
                    (counterparty_key, expected_direction)
                )
                if cp_balance is None:
                    kinds = counterparty_kinds.get(counterparty_key)
                    if kinds:
                        found_direction = sorted(kinds)[0]
                        mismatch_reason = "direction_mismatch"
                    else:
                        mismatch_reason = "missing_counterparty_balance"
            if cp_balance is None:
                mismatches.append(
                    {
                        "account_name": name,
                        "balance": str(bal),
                        "counterparty": counterparty,
                        "expected_direction": expected_direction,
                        "counterparty_direction": found_direction,
                        "counterparty_balance": None,
                        "reason": mismatch_reason or "missing_counterparty_balance",
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
                            "expected_direction": expected_direction,
                            "counterparty_direction": expected_direction,
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
                    message="Intercompany balance evaluated.",
                    values={
                        "account_name": name,
                        "period_end": ctx.period_end.isoformat(),
                        "balance": str(bal),
                        "counterparty": counterparty,
                        "expected_direction": expected_direction,
                        "counterparty_direction": found_direction or expected_direction,
                        "counterparty_balance": str(cp_balance) if cp_balance is not None else None,
                        "status": detail_status,
                    },
                )
            )

        status = RuleStatus.NEEDS_REVIEW if mismatches else RuleStatus.PASS
        summary = (
            "Intercompany balances require review (missing or mismatched counterpart balances)."
            if mismatches
            else f"Intercompany balances match counterpart Balance Sheets as of {ctx.period_end.isoformat()}."
        )
        human_action = (
            "Confirm counterpart balances and reconcile intercompany accounts."
            if mismatches
            else None
        )

        details.append(
            RuleResultDetail(
                key="intercompany_summary",
                message="Intercompany balance comparison summary.",
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
        return _extract_counterparty(name, patterns)
