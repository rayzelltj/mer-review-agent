from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import FixedAssetRegisterReconcilesRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import AccountBalance, RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule

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

_CONTRA_ASSET_NAME_HINTS = (
    "accumulated",
    "amortization",
    "amortisation",
    "depreciation",
    "depn",
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


def _strip_account_code_prefix(value: str) -> str:
    cleaned = _clean_text(value)
    return re.sub(r"^\d+\s*", "", cleaned).strip()


def _name_candidates(asset_class: str, account_name_match: str) -> list[str]:
    out: list[str] = []
    for raw in (account_name_match, asset_class):
        candidate = _clean_text(raw)
        if not candidate:
            continue
        for variant in (
            candidate,
            _strip_account_code_prefix(candidate),
            _strip_account_code_prefix(candidate).split(" - ", 1)[0].strip(),
        ):
            if variant and variant not in out:
                out.append(variant)
    return out


def _is_fixed_asset_account(acct: AccountBalance) -> bool:
    type_l = _normalize_name(acct.type or "")
    subtype_l = _normalize_name(acct.subtype or "")
    name_l = _normalize_name(acct.name or "")
    if "fixed asset" in type_l or "fixed asset" in subtype_l:
        return True
    return any(token in name_l for token in _FIXED_ASSET_NAME_HINTS)


def _is_contra_asset_name(name: str) -> bool:
    norm = _normalize_name(name)
    return any(token in norm for token in _CONTRA_ASSET_NAME_HINTS)


def _extract_register_rows(item: Any) -> list[dict[str, Any]]:
    meta = item.meta or {}
    rows: list[dict[str, Any]] = []

    meta_items = meta.get("items")
    if isinstance(meta_items, list):
        for meta_row in meta_items:
            if not isinstance(meta_row, dict):
                continue
            rows.append(
                {
                    "asset_class": _clean_text(meta_row.get("asset_class") or meta_row.get("name")),
                    "account_name_match": _clean_text(meta_row.get("account_name_match")),
                    "account_ref": _clean_text(meta_row.get("account_ref")),
                    "balance": _parse_decimal(
                        meta_row.get("balance")
                        or meta_row.get("amount")
                        or meta_row.get("closing_balance")
                        or meta_row.get("closing_balance_as_per_register")
                    ),
                    "uri": item.uri,
                    "as_of_date": item.as_of_date,
                }
            )
        return rows

    rows.append(
        {
            "asset_class": _clean_text(meta.get("asset_class") or meta.get("name")),
            "account_name_match": _clean_text(meta.get("account_name_match")),
            "account_ref": _clean_text(meta.get("account_ref")),
            "balance": _parse_decimal(
                item.amount
                if item.amount is not None
                else (
                    meta.get("balance")
                    or meta.get("amount")
                    or meta.get("closing_balance")
                    or meta.get("closing_balance_as_per_register")
                )
            ),
            "uri": item.uri,
            "as_of_date": item.as_of_date,
        }
    )
    return rows


def _find_balance_sheet_account(
    *,
    accounts: list[AccountBalance],
    account_ref: str,
    name_candidates: list[str],
    prefer_total: bool,
) -> tuple[AccountBalance | None, str | None, list[str]]:
    if account_ref:
        match = next((acct for acct in accounts if acct.account_ref == account_ref), None)
        if match is None:
            return None, "missing_account_ref", []
        return match, None, []

    normalized_candidates = [_normalize_name(name) for name in name_candidates if _normalize_name(name)]
    if not normalized_candidates:
        return None, "missing_name_match", []

    ranked: list[tuple[int, AccountBalance]] = []
    for acct in accounts:
        acct_name_norm = _normalize_name(acct.name or "")
        if not acct_name_norm:
            continue
        matched_candidate = next((cand for cand in normalized_candidates if cand in acct_name_norm), None)
        if matched_candidate is None:
            continue

        score = 0
        if prefer_total and acct_name_norm.startswith("total "):
            score += 40
        if acct_name_norm == matched_candidate:
            score += 200
        if acct_name_norm == f"total {matched_candidate}":
            score += 220
        if acct.account_ref.startswith("report::Total "):
            score += 70
        if _is_contra_asset_name(acct.name or ""):
            score -= 120
        if "fixed asset" in _normalize_name(acct.type or ""):
            score += 20
        ranked.append((score, acct))

    if not ranked:
        return None, "missing_account_match", []

    ranked.sort(key=lambda row: row[0], reverse=True)
    best_score = ranked[0][0]
    best_matches = [acct for score, acct in ranked if score == best_score]
    candidates = [acct.name for _score, acct in ranked[:5]]
    if len({acct.account_ref for acct in best_matches}) > 1:
        return None, "ambiguous_account_match", candidates
    return best_matches[0], None, candidates


@register_rule
class BS_FIXED_ASSET_REGISTER_RECONCILES(Rule):
    rule_id = "BS-FIXED-ASSET-REGISTER-RECONCILES"
    rule_title = "Fixed asset register reconciles to Balance Sheet"
    best_practices_reference = "Fixed assets"
    sources = ["Depreciation schedule / Fixed asset register", "QBO (Balance Sheet)"]
    config_model = FixedAssetRegisterReconcilesRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, FixedAssetRegisterReconcilesRuleConfig)
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

        in_scope_accounts = [acct for acct in ctx.balance_sheet.accounts if _is_fixed_asset_account(acct)]
        if not in_scope_accounts:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary=f"No fixed asset accounts found as of {ctx.period_end.isoformat()}.",
            )

        evidence_items = [item for item in ctx.evidence.items if item.evidence_type == cfg.evidence_type]
        if not evidence_items:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary=f"Missing fixed asset register/depreciation schedule evidence for {ctx.period_end.isoformat()}.",
                human_action=(
                    "Provide the month-end fixed asset register or depreciation schedule with closing balances by "
                    "asset class."
                ),
            )

        if cfg.require_evidence_as_of_date_match_period_end:
            mismatched_dates = [
                item for item in evidence_items if item.as_of_date is None or item.as_of_date != ctx.period_end
            ]
            if mismatched_dates:
                return RuleResult(
                    rule_id=self.rule_id,
                    rule_title=self.rule_title,
                    best_practices_reference=self.best_practices_reference,
                    sources=self.sources,
                    status=missing_status,
                    severity=severity_for_status(missing_status),
                    summary=(
                        "Fixed asset register/depreciation schedule as-of date is missing or does not match period "
                        "end; cannot verify."
                    ),
                    evidence_used=mismatched_dates,
                    human_action="Provide fixed asset evidence as of the period end date.",
                )

        register_rows: list[dict[str, Any]] = []
        for item in evidence_items:
            register_rows.extend(_extract_register_rows(item))

        valid_rows: list[dict[str, Any]] = []
        invalid_rows = 0
        for row in register_rows:
            has_identifier = bool(
                _clean_text(row.get("asset_class"))
                or _clean_text(row.get("account_name_match"))
                or _clean_text(row.get("account_ref"))
            )
            if row.get("balance") is None or not has_identifier:
                invalid_rows += 1
                continue
            valid_rows.append(row)

        if not valid_rows:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Fixed asset evidence is missing usable asset-class closing balances; cannot verify.",
                evidence_used=evidence_items,
                human_action=(
                    "Ensure the fixed asset register/depreciation schedule includes month-end closing balances by "
                    "asset class."
                ),
            )

        details: list[RuleResultDetail] = []
        fail_count = 0
        missing_count = 0

        for row in valid_rows:
            asset_class = _clean_text(row.get("asset_class"))
            account_name_match = _clean_text(row.get("account_name_match"))
            account_ref = _clean_text(row.get("account_ref"))
            register_balance = row["balance"]

            candidates = _name_candidates(asset_class, account_name_match)
            matched_acct, match_error, candidate_accounts = _find_balance_sheet_account(
                accounts=in_scope_accounts,
                account_ref=account_ref,
                name_candidates=candidates,
                prefer_total=cfg.prefer_total_balance_sheet_lines,
            )

            detail_key = matched_acct.account_ref if matched_acct is not None else f"asset_class::{asset_class or account_name_match or 'unknown'}"
            detail_status: RuleStatus
            difference: str | None = None
            bs_balance: str | None = None
            bs_account_name: str | None = None
            bs_account_ref: str | None = None
            if matched_acct is None:
                detail_status = missing_status
                missing_count += 1
            else:
                reg_q = quantize_amount(register_balance, cfg.amount_quantize)
                bs_q = quantize_amount(matched_acct.balance, cfg.amount_quantize)
                diff_q = abs(bs_q - reg_q)
                detail_status = RuleStatus.PASS if diff_q == 0 else RuleStatus.FAIL
                if detail_status == RuleStatus.FAIL:
                    fail_count += 1
                difference = str(diff_q)
                bs_balance = str(bs_q)
                bs_account_name = matched_acct.name
                bs_account_ref = matched_acct.account_ref
            details.append(
                RuleResultDetail(
                    key=detail_key,
                    message="Fixed asset class closing balance compared to Balance Sheet.",
                    values={
                        "asset_class": asset_class or None,
                        "account_name_match": account_name_match or None,
                        "period_end": ctx.period_end.isoformat(),
                        "register_closing_balance": str(register_balance),
                        "bs_account_ref": bs_account_ref,
                        "bs_account_name": bs_account_name,
                        "bs_balance": bs_balance,
                        "difference": difference,
                        "match_error": match_error,
                        "candidate_accounts": candidate_accounts,
                        "evidence_type": cfg.evidence_type,
                        "evidence_as_of_date": row.get("as_of_date").isoformat()
                        if row.get("as_of_date") is not None
                        else None,
                        "evidence_uri": row.get("uri"),
                        "status": detail_status.value,
                    },
                )
            )

        if invalid_rows:
            missing_count += 1
            details.append(
                RuleResultDetail(
                    key="fixed_asset_register_input",
                    message="Fixed asset evidence row quality check.",
                    values={
                        "period_end": ctx.period_end.isoformat(),
                        "valid_rows_count": len(valid_rows),
                        "invalid_rows_count": invalid_rows,
                        "status": missing_status.value,
                    },
                )
            )

        if fail_count > 0:
            overall = RuleStatus.FAIL
            summary = (
                f"Fixed asset register/depreciation schedule does not reconcile to Balance Sheet for "
                f"{fail_count} asset class(es)."
            )
            human_action = (
                "Review and update the depreciation schedule/fixed asset register, reconcile to QBO fixed asset "
                "balances, and link support in the delivery file."
            )
        elif missing_count > 0:
            overall = missing_status
            summary = "Missing or ambiguous fixed asset class mappings prevented complete reconciliation."
            human_action = (
                "Add account mapping (account_ref or account_name_match) for each asset class and provide complete "
                "closing balances."
            )
        else:
            overall = RuleStatus.PASS
            summary = f"Fixed asset register/depreciation schedule reconciles to Balance Sheet as of {ctx.period_end.isoformat()}."
            human_action = None

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=overall,
            severity=severity_for_status(overall),
            summary=summary,
            details=details,
            evidence_used=evidence_items,
            human_action=human_action,
        )
