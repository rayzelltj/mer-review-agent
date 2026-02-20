from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import FixedAssetCapitalizationThresholdRuleConfig
from ..models import (
    AccountBalance,
    EvidenceItem,
    RuleResult,
    RuleResultDetail,
    RuleStatus,
    StatusOrdering,
    severity_for_status,
)
from ..registry import register_rule
from ..rule import Rule
from ..context import RuleContext, quantize_amount

_FIXED_ASSET_NAME_HINTS = (
    "fixed asset",
    "equipment",
    "furnishings",
    "furniture",
    "leasehold",
    "vehicle",
    "building",
    "website",
    "computer",
)

_THRESHOLD_TEXT_PATTERNS = (
    re.compile(
        r"(?is)(?:capitali[sz]ation(?:\s+threshold)?|fixed\s+assets?)"
        r".{0,120}?(?:greater\s+than|over|above|at\s+least|minimum(?:\s+of)?|threshold(?:\s+is|:| of)?)"
        r"[^\d$]{0,20}\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
    ),
    re.compile(
        r"(?is)threshold.{0,80}\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
    ),
)


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        s = s.replace(",", "").replace("$", "").replace("\u00a0", "").strip()
        if s.startswith("(") and s.endswith(")"):
            s = f"-{s[1:-1].strip()}"
        if s in {"-", "--", "- -", "n/a"}:
            return None
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _is_fixed_asset_account(acct: AccountBalance) -> bool:
    if "report::" in (acct.account_ref or ""):
        return False
    type_l = _normalize_name(acct.type or "")
    subtype_l = _normalize_name(acct.subtype or "")
    name_l = _normalize_name(acct.name or "")
    if "fixed asset" in type_l or "fixed asset" in subtype_l:
        return True
    return any(token in name_l for token in _FIXED_ASSET_NAME_HINTS)


def _latest_prior_snapshot(ctx: RuleContext):
    if not ctx.prior_balance_sheets:
        return None
    return max(
        (bs for bs in ctx.prior_balance_sheets if bs.as_of_date < ctx.period_end),
        default=None,
        key=lambda bs: bs.as_of_date,
    )


def _balance_for_account(snapshot, account_ref: str) -> Decimal | None:
    for acct in snapshot.accounts:
        if acct.account_ref == account_ref:
            return acct.balance
    return None


def _parse_threshold_from_text(text: str) -> Decimal | None:
    content = _clean_text(text)
    if not content:
        return None
    for pattern in _THRESHOLD_TEXT_PATTERNS:
        match = pattern.search(content)
        if not match:
            continue
        parsed = _parse_decimal(match.group(1))
        if parsed is not None:
            return abs(parsed)
    return None


def _extract_threshold_from_object(value: Any) -> Decimal | None:
    if isinstance(value, (Decimal, int, float, str)):
        parsed = _parse_decimal(value)
        if parsed is not None:
            return abs(parsed)
        if isinstance(value, str):
            return _parse_threshold_from_text(value)
        return None

    if isinstance(value, dict):
        for key in (
            "fixed_asset_capitalization_threshold",
            "capitalization_threshold",
            "capitalization_threshold_amount",
            "threshold",
            "amount",
        ):
            parsed = _extract_threshold_from_object(value.get(key))
            if parsed is not None:
                return parsed
        for item in value.values():
            parsed = _extract_threshold_from_object(item)
            if parsed is not None:
                return parsed
    elif isinstance(value, list):
        for item in value:
            parsed = _extract_threshold_from_object(item)
            if parsed is not None:
                return parsed
    return None


def _extract_kyc_threshold(evidence_items: list[EvidenceItem]) -> tuple[Decimal | None, str | None]:
    for item in evidence_items:
        from_amount = _parse_decimal(item.amount)
        if from_amount is not None and from_amount > 0:
            return abs(from_amount), "amount"

        meta = item.meta or {}
        threshold = _extract_threshold_from_object(meta)
        if threshold is not None:
            return threshold, "meta"

        text_candidates = [
            _clean_text(meta.get("text")),
            _clean_text(meta.get("content")),
            _clean_text(meta.get("raw_text")),
            _clean_text(meta.get("fixed_assets")),
            _clean_text(meta.get("fixed_asset_section")),
        ]
        for text in text_candidates:
            threshold = _parse_threshold_from_text(text)
            if threshold is not None:
                return threshold, "text"
    return None, None


def _account_id_from_ref(account_ref: str) -> str:
    raw = _clean_text(account_ref)
    if not raw:
        return ""
    if "::" in raw:
        return raw.split("::")[-1].strip()
    return raw


def _extract_txn_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = _clean_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _ledger_transactions_by_account(
    evidence_items: list[EvidenceItem],
    *,
    period_start: date,
    period_end: date,
    max_per_account: int,
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for item in evidence_items:
        meta = item.meta or {}
        account_ref = _clean_text(meta.get("account_ref"))
        account_id = _clean_text(meta.get("account_id"))
        rows = meta.get("transactions")
        if not isinstance(rows, list):
            continue
        parsed_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            txn_date = _extract_txn_date(row.get("txn_date") or row.get("date"))
            amount = _parse_decimal(row.get("amount"))
            if txn_date is None or amount is None:
                continue
            if txn_date < period_start or txn_date > period_end:
                continue
            parsed_rows.append(
                {
                    "txn_date": txn_date,
                    "amount": amount,
                    "description": _clean_text(row.get("description") or row.get("memo")),
                    "txn_type": _clean_text(row.get("txn_type") or row.get("type")),
                }
            )
        parsed_rows.sort(key=lambda row: row["txn_date"])
        if max_per_account > 0:
            parsed_rows = parsed_rows[:max_per_account]
        for key in (account_ref, account_id):
            if key:
                out.setdefault(key, []).extend(parsed_rows)
    return out


def _is_ignored_expense(name: str, patterns: list[str]) -> bool:
    norm = _normalize_name(name)
    if not norm:
        return False
    return any(_normalize_name(pattern) in norm for pattern in patterns)


def _dedupe_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[EvidenceItem] = []
    for item in items:
        key = (
            item.evidence_type,
            item.source,
            item.uri,
            item.as_of_date,
            item.statement_end_date,
            str(item.amount) if item.amount is not None else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


@register_rule
class BS_FIXED_ASSET_CAPITALIZATION_THRESHOLD(Rule):
    rule_id = "BS-FIXED-ASSET-CAPITALIZATION-THRESHOLD"
    rule_title = "Capitalization threshold enforced"
    best_practices_reference = "Fixed assets"
    sources = ["QBO (Balance Sheet)", "QBO (ledger and P&L)", "Google Drive (KYC)"]
    config_model = FixedAssetCapitalizationThresholdRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(
            self.rule_id,
            FixedAssetCapitalizationThresholdRuleConfig,
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

        fixed_asset_accounts = [acct for acct in ctx.balance_sheet.accounts if _is_fixed_asset_account(acct)]
        if not fixed_asset_accounts:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No fixed asset accounts found as of {ctx.period_end.isoformat()}.",
            )

        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []
        evidence_used: list[EvidenceItem] = []
        ordering = StatusOrdering.default()

        capitalization_violations = 0
        abnormal_expense_changes = 0
        period_start = ctx.period_end.replace(day=1)

        prior_snapshot = _latest_prior_snapshot(ctx)
        if prior_snapshot is None:
            statuses.append(missing_status)
            details.append(
                RuleResultDetail(
                    key="fixed_assets_prior_month_missing",
                    message="Cannot compare fixed asset balances without a prior-month balance sheet snapshot.",
                    values={
                        "sub_rule": "fixed_asset_increment_threshold",
                        "period_end": ctx.period_end.isoformat(),
                        "status": missing_status.value,
                    },
                )
            )
        else:
            increments: list[dict[str, Any]] = []
            for acct in fixed_asset_accounts:
                prior_balance = _balance_for_account(prior_snapshot, acct.account_ref) or Decimal("0")
                delta = acct.balance - prior_balance
                if delta > 0:
                    increments.append(
                        {
                            "account_ref": acct.account_ref,
                            "account_name": acct.name,
                            "prior_balance": prior_balance,
                            "current_balance": acct.balance,
                            "increase": delta,
                        }
                    )

            if not increments:
                statuses.append(RuleStatus.PASS)
                details.append(
                    RuleResultDetail(
                        key="fixed_assets_no_increment",
                        message="No month-over-month increase in fixed asset balances.",
                        values={
                            "sub_rule": "fixed_asset_increment_threshold",
                            "period_end": ctx.period_end.isoformat(),
                            "prior_period_end": prior_snapshot.as_of_date.isoformat(),
                            "status": RuleStatus.PASS.value,
                        },
                    )
                )
            else:
                kyc_items = [item for item in ctx.evidence.items if item.evidence_type == cfg.kyc_evidence_type]
                threshold, threshold_source = _extract_kyc_threshold(kyc_items)
                if threshold is None and cfg.require_kyc_threshold_when_fixed_asset_increase:
                    statuses.append(missing_status)
                    details.append(
                        RuleResultDetail(
                            key="fixed_assets_kyc_threshold_missing",
                            message="Fixed asset balance increased, but capitalization threshold was not found in KYC evidence.",
                            values={
                                "sub_rule": "fixed_asset_increment_threshold",
                                "period_end": ctx.period_end.isoformat(),
                                "kyc_evidence_type": cfg.kyc_evidence_type,
                                "increment_account_count": len(increments),
                                "status": missing_status.value,
                            },
                        )
                    )
                else:
                    if kyc_items:
                        evidence_used.extend(kyc_items)

                    ledger_items = [
                        item
                        for item in ctx.evidence.items
                        if item.evidence_type == cfg.fixed_asset_ledger_evidence_type
                    ]
                    if not ledger_items and cfg.require_ledger_transactions_when_fixed_asset_increase:
                        statuses.append(missing_status)
                        details.append(
                            RuleResultDetail(
                                key="fixed_assets_ledger_missing",
                                message="Fixed asset balance increased, but no fixed asset ledger transaction evidence was provided.",
                                values={
                                    "sub_rule": "fixed_asset_increment_threshold",
                                    "period_end": ctx.period_end.isoformat(),
                                    "ledger_evidence_type": cfg.fixed_asset_ledger_evidence_type,
                                    "status": missing_status.value,
                                },
                            )
                        )
                    else:
                        if ledger_items:
                            evidence_used.extend(ledger_items)
                        tx_by_account = _ledger_transactions_by_account(
                            ledger_items,
                            period_start=period_start,
                            period_end=ctx.period_end,
                            max_per_account=int(cfg.max_transactions_to_evaluate_per_account or 0),
                        )

                        for inc in increments:
                            account_ref = inc["account_ref"]
                            account_id = _account_id_from_ref(account_ref)
                            txns = tx_by_account.get(account_ref) or tx_by_account.get(account_id) or []
                            if not txns:
                                statuses.append(missing_status)
                                details.append(
                                    RuleResultDetail(
                                        key=account_ref,
                                        message="No fixed asset ledger transactions found for an account with a positive month-over-month increase.",
                                        values={
                                            "sub_rule": "fixed_asset_increment_threshold",
                                            "account_ref": account_ref,
                                            "account_name": inc["account_name"],
                                            "increase": str(
                                                quantize_amount(inc["increase"], cfg.amount_quantize)
                                            ),
                                            "period_end": ctx.period_end.isoformat(),
                                            "status": missing_status.value,
                                        },
                                    )
                                )
                                continue

                            candidate_additions = [row for row in txns if row["amount"] > 0]
                            if not candidate_additions:
                                statuses.append(missing_status)
                                details.append(
                                    RuleResultDetail(
                                        key=account_ref,
                                        message="Ledger transactions were found, but no positive additions were identified for capitalization-threshold testing.",
                                        values={
                                            "sub_rule": "fixed_asset_increment_threshold",
                                            "account_ref": account_ref,
                                            "account_name": inc["account_name"],
                                            "increase": str(
                                                quantize_amount(inc["increase"], cfg.amount_quantize)
                                            ),
                                            "period_end": ctx.period_end.isoformat(),
                                            "status": missing_status.value,
                                        },
                                    )
                                )
                                continue

                            for idx, txn in enumerate(candidate_additions, start=1):
                                txn_amount = abs(txn["amount"])
                                if threshold is None:
                                    txn_status = missing_status
                                elif txn_amount < threshold:
                                    txn_status = RuleStatus(cfg.capitalization_violation_status.value)
                                    capitalization_violations += 1
                                else:
                                    txn_status = RuleStatus.PASS
                                statuses.append(txn_status)
                                details.append(
                                    RuleResultDetail(
                                        key=f"{account_ref}:{idx}",
                                        message="Fixed asset transaction tested against capitalization threshold.",
                                        values={
                                            "sub_rule": "fixed_asset_increment_threshold",
                                            "account_ref": account_ref,
                                            "account_name": inc["account_name"],
                                            "txn_date": txn["txn_date"].isoformat(),
                                            "txn_type": txn["txn_type"],
                                            "description": txn["description"],
                                            "txn_amount": str(
                                                quantize_amount(txn_amount, cfg.amount_quantize)
                                            ),
                                            "threshold": (
                                                str(quantize_amount(threshold, cfg.amount_quantize))
                                                if threshold is not None
                                                else None
                                            ),
                                            "threshold_source": threshold_source,
                                            "increase": str(
                                                quantize_amount(inc["increase"], cfg.amount_quantize)
                                            ),
                                            "period_end": ctx.period_end.isoformat(),
                                            "status": txn_status.value,
                                        },
                                    )
                                )

        pnl_items = [
            item for item in ctx.evidence.items if item.evidence_type == cfg.pnl_expense_monthly_evidence_type
        ]
        if not pnl_items:
            statuses.append(missing_status)
            details.append(
                RuleResultDetail(
                    key="pnl_expense_monthly_missing",
                    message="Month-over-month expense analysis evidence is missing.",
                    values={
                        "sub_rule": "expense_abnormal_change",
                        "period_end": ctx.period_end.isoformat(),
                        "pnl_evidence_type": cfg.pnl_expense_monthly_evidence_type,
                        "status": missing_status.value,
                    },
                )
            )
        else:
            pnl_item = pnl_items[0]
            evidence_used.append(pnl_item)
            lines = (pnl_item.meta or {}).get("lines")
            if not isinstance(lines, list):
                statuses.append(missing_status)
                details.append(
                    RuleResultDetail(
                        key="pnl_expense_monthly_invalid",
                        message="Month-over-month expense evidence does not include valid line-level data.",
                        values={
                            "sub_rule": "expense_abnormal_change",
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                )
            else:
                flagged: list[dict[str, Any]] = []
                for line in lines:
                    if not isinstance(line, dict):
                        continue
                    name = _clean_text(line.get("name"))
                    if not name:
                        continue
                    if _is_ignored_expense(name, list(cfg.ignore_expense_name_patterns or [])):
                        continue

                    current_amount = _parse_decimal(line.get("current_amount"))
                    prior_amount = _parse_decimal(line.get("prior_amount"))
                    if current_amount is None or prior_amount is None:
                        continue

                    delta = current_amount - prior_amount
                    if prior_amount == 0:
                        abs_pct = None
                        is_abnormal = current_amount != 0
                    else:
                        abs_pct = abs(delta) / abs(prior_amount)
                        is_abnormal = abs_pct >= abs(Decimal(cfg.abnormal_change_pct))

                    if is_abnormal:
                        flagged.append(
                            {
                                "name": name,
                                "current_amount": current_amount,
                                "prior_amount": prior_amount,
                                "delta": delta,
                                "abs_pct_change": abs_pct,
                            }
                        )

                abnormal_expense_changes = len(flagged)
                if flagged:
                    abnormal_status = RuleStatus(cfg.abnormal_expense_change_status.value)
                    statuses.append(abnormal_status)
                    max_lines = max(int(cfg.max_flagged_expense_lines or 0), 1)
                    for idx, row in enumerate(flagged[:max_lines], start=1):
                        details.append(
                            RuleResultDetail(
                                key=f"expense_change:{idx}",
                                message="Abnormal month-over-month expense change detected (payroll/COGS excluded).",
                                values={
                                    "sub_rule": "expense_abnormal_change",
                                    "expense_name": row["name"],
                                    "current_amount": str(
                                        quantize_amount(row["current_amount"], cfg.amount_quantize)
                                    ),
                                    "prior_amount": str(
                                        quantize_amount(row["prior_amount"], cfg.amount_quantize)
                                    ),
                                    "delta": str(quantize_amount(row["delta"], cfg.amount_quantize)),
                                    "abs_pct_change": (
                                        str(row["abs_pct_change"]) if row["abs_pct_change"] is not None else None
                                    ),
                                    "threshold_pct": str(cfg.abnormal_change_pct),
                                    "status": abnormal_status.value,
                                },
                            )
                        )
                    if len(flagged) > max_lines:
                        details.append(
                            RuleResultDetail(
                                key="expense_change:truncated",
                                message="Additional abnormal expense lines were detected but omitted from detail payload.",
                                values={
                                    "sub_rule": "expense_abnormal_change",
                                    "abnormal_count_total": len(flagged),
                                    "abnormal_count_returned": max_lines,
                                    "status": abnormal_status.value,
                                },
                            )
                        )
                else:
                    statuses.append(RuleStatus.PASS)
                    details.append(
                        RuleResultDetail(
                            key="expense_change:none",
                            message="No abnormal month-over-month expense changes above threshold (payroll/COGS excluded).",
                            values={
                                "sub_rule": "expense_abnormal_change",
                                "threshold_pct": str(cfg.abnormal_change_pct),
                                "status": RuleStatus.PASS.value,
                            },
                        )
                    )

        final_status = ordering.worst(statuses)

        if final_status == RuleStatus.FAIL:
            summary = (
                "Fixed asset capitalization threshold violations detected; one or more additions appear below "
                f"threshold ({capitalization_violations} flagged)."
            )
            human_action = (
                "Review flagged fixed asset additions and reclassify below-threshold items to expense unless "
                "an exception is documented in the client policy."
            )
        elif final_status == RuleStatus.WARN:
            summary = (
                "Abnormal month-over-month expense changes detected (excluding payroll and COGS): "
                f"{abnormal_expense_changes} line(s)."
            )
            human_action = (
                "Review flagged expense lines for unusual movement and confirm any capitalization decisions are "
                "consistent with policy."
            )
        elif final_status == RuleStatus.NEEDS_REVIEW:
            summary = (
                "Insufficient prior-month/KYC/ledger/P&L evidence to complete fixed-asset capitalization "
                "threshold testing."
            )
            human_action = (
                "Provide prior-month balance sheet data, KYC capitalization threshold evidence, fixed-asset "
                "ledger transactions for the period, and monthly P&L expense-line comparisons."
            )
        elif final_status == RuleStatus.PASS:
            summary = (
                "Fixed asset capitalization threshold checks passed and no abnormal month-over-month non-payroll/"
                "non-COGS expense changes were detected."
            )
            human_action = None
        else:
            summary = "Rule not applicable."
            human_action = None

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=final_status,
            severity=severity_for_status(final_status),
            summary=summary,
            details=details,
            evidence_used=_dedupe_evidence(evidence_used),
            human_action=human_action,
        )
