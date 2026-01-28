from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from ..config import UnclearedItemsInvestigatedAndFlaggedRuleConfig
from ..context import RuleContext
from ..models import (
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


def _shift_months(d: date, months: int) -> date:
    """
    Shift `d` by `months` calendar months (negative allowed), clamping the day to the end of the target month.

    We intentionally use calendar months (not 30/60 day approximations) to match accounting expectations like
    "older than 2 months as of period end".
    """
    total_months = (d.year * 12 + (d.month - 1)) + months
    year = total_months // 12
    month = (total_months % 12) + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Prefer ISO; also support common reconciliation report format "DD/MM/YYYY" (per provided example).
        if "/" in s:
            parts = s.split("/")
            if len(parts) == 3:
                try:
                    dd, mm, yyyy = (int(p) for p in parts)
                    return date(yyyy, mm, dd)
                except Exception:
                    return None
        try:
            return date.fromisoformat(s)
        except Exception:
            return None
    return None


def _as_list(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if isinstance(value, list):
        out: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(item)
        return out
    return None


def _get_uncleared_items_meta(meta: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    """
    Canonical shape (preferred):
      meta["uncleared_items"] = {"as_at": [...], "after_date": [...]}

    Back-compat / adapter convenience:
      meta["uncleared_items_as_at"] = [...]
      meta["uncleared_items_after_date"] = [...]
    """
    bucket = meta.get("uncleared_items")
    if isinstance(bucket, dict):
        as_at = _as_list(bucket.get("as_at"))
        after = _as_list(bucket.get("after_date"))
        return as_at, after
    return _as_list(meta.get("uncleared_items_as_at")), _as_list(meta.get("uncleared_items_after_date"))


@register_rule
class BS_UNCLEARED_ITEMS_INVESTIGATED_AND_FLAGGED(Rule):
    rule_id = "BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED"
    rule_title = "Uncleared transactions are investigated and explained"
    best_practices_reference = "Bank reconciliations → Uncleared items"
    sources = ["Reconciliation report (detailed)"]
    config_model = UnclearedItemsInvestigatedAndFlaggedRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, UnclearedItemsInvestigatedAndFlaggedRuleConfig)
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

        recs = list(ctx.reconciliations)
        ordering = StatusOrdering.default()

        # Scope: if expected accounts are configured, enforce them (missing snapshots are missing_data_policy).
        # Otherwise, evaluate all provided snapshots.
        if cfg.expected_accounts:
            required_refs = list(cfg.expected_accounts)
        else:
            required_refs = [r.account_ref for r in recs]

        if not required_refs:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary=f"No reconciliation snapshots provided for {ctx.period_end.isoformat()}; cannot evaluate uncleared items.",
                human_action="Provide reconciliation detailed report data (uncleared items as at statement end date).",
            )

        name_by_ref = {a.account_ref: a.name for a in ctx.balance_sheet.accounts}

        statuses: list[RuleStatus] = []
        details: list[RuleResultDetail] = []

        for account_ref in required_refs:
            account_name = name_by_ref.get(account_ref, "")
            candidates = [r for r in recs if r.account_ref == account_ref]
            if not candidates:
                statuses.append(missing_status)
                details.append(
                    RuleResultDetail(
                        key=account_ref,
                        message="Missing reconciliation snapshot for this account; cannot evaluate uncleared items.",
                        values={
                            "account_name": account_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                            "expected_from_maintenance": bool(cfg.expected_accounts),
                        },
                    )
                )
                continue

            latest = max(candidates, key=lambda r: r.statement_end_date or date.min)
            status, detail = self._evaluate_one(ctx, latest, cfg, account_name_fallback=account_name)
            statuses.append(status)
            details.append(detail)

        overall = ordering.worst(statuses)
        severity = severity_for_status(overall)

        exemplar = next((d for d in details if d.values.get("status") == overall.value), None)
        if overall == RuleStatus.PASS:
            summary = "No stale uncleared items detected (across evaluated accounts)."
        elif overall in (RuleStatus.WARN, RuleStatus.FAIL) and exemplar:
            summary = (
                f"Uncleared items older than {cfg.months_old_threshold} month(s) exist for "
                f"'{exemplar.values.get('account_name','')}' as of {exemplar.values.get('as_at_date','')}; "
                "investigate and explain."
            )
        elif overall == RuleStatus.NEEDS_REVIEW:
            summary = f"Missing data prevented evaluation of uncleared items as of {ctx.period_end.isoformat()}."
        else:
            summary = "Not applicable."

        human_action = None
        if overall in (RuleStatus.WARN, RuleStatus.FAIL, RuleStatus.NEEDS_REVIEW):
            human_action = (
                "Review uncleared items as at the reconciliation statement end date; "
                f"flag any items older than {cfg.months_old_threshold} month(s) and check with the client for "
                "explanations or corrections."
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
        cfg: UnclearedItemsInvestigatedAndFlaggedRuleConfig,
        *,
        account_name_fallback: str,
    ) -> tuple[RuleStatus, RuleResultDetail]:
        account_name = getattr(rec, "account_name", "") or account_name_fallback
        missing_status = RuleStatus(cfg.missing_data_policy.value)

        as_at_date = rec.statement_end_date
        if as_at_date is None:
            return (
                missing_status,
                RuleResultDetail(
                    key=rec.account_ref,
                    message="Missing statement end date; cannot evaluate uncleared item age.",
                    values={
                        "account_name": account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "status": missing_status.value,
                    },
                ),
            )

        as_at_items, after_date_items = _get_uncleared_items_meta(rec.meta or {})
        if as_at_items is None:
            return (
                missing_status,
                RuleResultDetail(
                    key=rec.account_ref,
                    message="Missing uncleared items (as at statement end date) in reconciliation metadata.",
                    values={
                        "account_name": account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "as_at_date": as_at_date.isoformat(),
                        "status": missing_status.value,
                    },
                ),
            )

        threshold_date = _shift_months(as_at_date, -int(cfg.months_old_threshold or 0))

        flagged: list[dict[str, Any]] = []
        invalid_count = 0

        for item in as_at_items:
            txn_date = _parse_date(item.get("txn_date") or item.get("date") or item.get("transaction_date"))
            if txn_date is None:
                invalid_count += 1
                continue
            if txn_date < threshold_date:
                flagged.append(
                    {
                        "txn_date": txn_date.isoformat(),
                        "description": item.get("description") or item.get("memo") or item.get("name") or "",
                        "amount": item.get("amount"),
                        "type": item.get("type") or item.get("txn_type") or "",
                        "reference": item.get("reference") or item.get("ref") or "",
                    }
                )

        if invalid_count:
            status = missing_status
        elif flagged:
            status = cfg.stale_item_status
        else:
            status = RuleStatus.PASS

        ignored_after_count = len(after_date_items or [])
        flagged_sorted = sorted(flagged, key=lambda x: x.get("txn_date") or "")
        flagged_sample = flagged_sorted[: max(0, int(cfg.max_flagged_items_in_detail or 0))]

        return (
            status,
            RuleResultDetail(
                key=rec.account_ref,
                message="Uncleared items age evaluated (as at statement end date; 'after date' items ignored).",
                values={
                    "account_name": account_name,
                    "period_end": ctx.period_end.isoformat(),
                    "as_at_date": as_at_date.isoformat(),
                    "months_old_threshold": int(cfg.months_old_threshold or 0),
                    "threshold_date": threshold_date.isoformat(),
                    "uncleared_items_as_at_count": len(as_at_items),
                    "uncleared_items_after_date_ignored_count": ignored_after_count,
                    "invalid_uncleared_item_date_count": invalid_count,
                    "flagged_uncleared_items_count": len(flagged),
                    "flagged_uncleared_items_sample": flagged_sample,
                    "status": status.value,
                },
            ),
        )
