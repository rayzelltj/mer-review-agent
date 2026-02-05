from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from ..config import TaxFilingsUpToDateRuleConfig
from ..context import RuleContext
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@dataclass(frozen=True)
class _TaxAgency:
    agency_id: str
    display_name: str
    last_file_date: date | None
    tax_tracked_on_sales: bool


@dataclass(frozen=True)
class _TaxReturn:
    agency_id: str
    start_date: date | None
    end_date: date | None
    file_date: date | None


def _iter_items(meta: dict[str, Any]) -> Iterable[dict[str, Any]]:
    items = meta.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                yield item


def _infer_months_between(start: date, end: date) -> int | None:
    if end < start:
        return None
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    return months if months > 0 else None


def _last_day_of_month(dt: date) -> date:
    next_month = dt.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


def _is_month_end(dt: date) -> bool:
    return dt == _last_day_of_month(dt)


def _add_months(dt: date, months: int) -> date:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    candidate = _safe_date(year, month, dt.day)
    if _is_month_end(dt):
        return _last_day_of_month(candidate)
    return candidate


def _safe_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        return _last_day_of_month(date(year, month, 1))


def _expected_period_end(
    period_end: date, cadence_months: int, anchor_end: date | None
) -> date | None:
    if cadence_months not in (1, 3, 12):
        return None
    if anchor_end is None:
        return None
    current = anchor_end
    if current > period_end:
        while current > period_end:
            current = _add_months(current, -cadence_months)
        return current
    while True:
        next_end = _add_months(current, cadence_months)
        if next_end > period_end:
            return current
        current = next_end


@register_rule
class BS_TAX_FILINGS_UP_TO_DATE(Rule):
    rule_id = "BS-TAX-FILINGS-UP-TO-DATE"
    rule_title = "Sales tax filings completed through most recent period"
    best_practices_reference = "Tax accounts"
    sources = ["QBO (TaxAgency, TaxReturn)"]
    config_model = TaxFilingsUpToDateRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, TaxFilingsUpToDateRuleConfig)
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

        agencies_item = ctx.evidence.first(cfg.tax_agencies_evidence_type)
        returns_item = ctx.evidence.first(cfg.tax_returns_evidence_type)
        if agencies_item is None or returns_item is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Missing tax agency/return data; cannot verify filings.",
                evidence_used=[item for item in [agencies_item, returns_item] if item],
                human_action="Provide TaxAgency and TaxReturn data from QBO.",
            )

        agencies = [
            _TaxAgency(
                agency_id=str(item.get("id") or ""),
                display_name=str(item.get("display_name") or ""),
                last_file_date=item.get("last_file_date"),
                tax_tracked_on_sales=bool(item.get("tax_tracked_on_sales")),
            )
            for item in _iter_items(agencies_item.meta or {})
        ]
        returns = [
            _TaxReturn(
                agency_id=str(item.get("agency_id") or ""),
                start_date=item.get("start_date"),
                end_date=item.get("end_date"),
                file_date=item.get("file_date"),
            )
            for item in _iter_items(returns_item.meta or {})
        ]

        if not agencies or not returns:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Tax agency/return data is empty; cannot verify filings.",
                evidence_used=[agencies_item, returns_item],
                human_action="Confirm TaxAgency and TaxReturn exports contain data.",
            )

        exclude_patterns = [p.lower() for p in cfg.exclude_agency_name_patterns]
        agencies = [
            agency
            for agency in agencies
            if agency.tax_tracked_on_sales
            and not any(p in agency.display_name.lower() for p in exclude_patterns)
        ]
        if not agencies:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary="No sales tax agencies tracked on sales; not applicable.",
                evidence_used=[agencies_item],
            )

        details: list[RuleResultDetail] = []
        overall_status = RuleStatus.PASS
        status_rank = {
            RuleStatus.PASS: 0,
            RuleStatus.NOT_APPLICABLE: 1,
            RuleStatus.NEEDS_REVIEW: 2,
            RuleStatus.WARN: 3,
            RuleStatus.FAIL: 4,
        }

        for agency in agencies:
            agency_returns = [r for r in returns if r.agency_id == agency.agency_id]
            # Consider all filed returns; filings can happen after period end.
            filed_returns = [r for r in agency_returns if r.file_date is not None]
            if not filed_returns:
                if status_rank[missing_status] > status_rank[overall_status]:
                    overall_status = missing_status
                details.append(
                    RuleResultDetail(
                        key=agency.agency_id or agency.display_name,
                        message="No filed tax returns found for agency.",
                        values={
                            "agency_name": agency.display_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                )
                continue

            # Coverage is based on the latest period end among filed returns.
            latest_filed = max(
                filed_returns, key=lambda r: r.end_date or r.file_date or date.min
            )
            if latest_filed.start_date is None or latest_filed.end_date is None:
                if status_rank[missing_status] > status_rank[overall_status]:
                    overall_status = missing_status
                details.append(
                    RuleResultDetail(
                        key=agency.agency_id or agency.display_name,
                        message="Latest filed return missing period dates.",
                        values={
                            "agency_name": agency.display_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                )
                continue

            cadence_months = _infer_months_between(
                latest_filed.start_date, latest_filed.end_date
            )
            expected_end = _expected_period_end(
                ctx.period_end,
                cadence_months or -1,
                latest_filed.end_date,
            )
            if expected_end is None:
                if status_rank[missing_status] > status_rank[overall_status]:
                    overall_status = missing_status
                details.append(
                    RuleResultDetail(
                        key=agency.agency_id or agency.display_name,
                        message="Unable to infer tax filing cadence for agency.",
                        values={
                            "agency_name": agency.display_name,
                            "period_end": ctx.period_end.isoformat(),
                            "latest_filed_start": latest_filed.start_date.isoformat(),
                            "latest_filed_end": latest_filed.end_date.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                )
                continue

            if latest_filed.end_date >= expected_end:
                status = RuleStatus.PASS
            else:
                status = cfg.delinquent_status

            if status_rank[status] > status_rank[overall_status]:
                overall_status = status

            details.append(
                RuleResultDetail(
                    key=agency.agency_id or agency.display_name,
                    message="Tax filing cadence evaluated for agency.",
                    values={
                        "agency_name": agency.display_name,
                        "period_end": ctx.period_end.isoformat(),
                        "latest_filed_start": latest_filed.start_date.isoformat(),
                        "latest_filed_end": latest_filed.end_date.isoformat(),
                        "latest_file_date": latest_filed.file_date.isoformat()
                        if latest_filed.file_date
                        else None,
                        "expected_period_end": expected_end.isoformat(),
                        "cadence_months": cadence_months,
                        "status": status.value,
                    },
                )
            )

        summary = (
            f"Sales tax filings are up to date through {ctx.period_end.isoformat()}."
            if overall_status == RuleStatus.PASS
            else "Sales tax filings are not up to date for one or more agencies."
        )
        if overall_status == missing_status:
            summary = "Missing or incomplete tax return data; cannot verify filings."

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=overall_status,
            severity=severity_for_status(overall_status),
            summary=summary,
            details=details,
            evidence_used=[agencies_item, returns_item],
            human_action=(
                "File missing sales tax returns and document filing periods."
                if overall_status == cfg.delinquent_status
                else None
            ),
        )
