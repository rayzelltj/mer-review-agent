from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from ..config import TaxPayableAndSuspenseReconcileRuleConfig
from ..context import RuleContext
from ..models import RuleResult, RuleResultDetail, RuleStatus, severity_for_status
from ..registry import register_rule
from ..rule import Rule


@dataclass(frozen=True)
class _TaxAgency:
    agency_id: str
    display_name: str


@dataclass(frozen=True)
class _TaxReturn:
    agency_id: str
    start_date: date | None
    end_date: date | None
    file_date: date | None
    net_tax_amount_due: Decimal | None
    upcoming_filing: bool = False


@dataclass(frozen=True)
class _TaxPayment:
    payment_date: date | None
    payment_amount: Decimal | None
    refund: bool
    agency_id: str | None


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


def _iter_items(meta: dict[str, Any]) -> Iterable[dict[str, Any]]:
    items = meta.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                yield item


def _to_date(value: Any) -> date | None:
    """Coerce a str, date, or datetime to a date object; return None on failure."""
    if value is None:
        return None
    if isinstance(value, date):
        return value if not hasattr(value, "date") else value.date()  # type: ignore[union-attr]
    if isinstance(value, str):
        val = value.strip()
        if not val:
            return None
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None
    return None


def _name_matches(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    return any(pat in lowered for pat in patterns)


def _infer_agency_for_account(account_name: str, agencies: list[_TaxAgency]) -> str | None:
    lowered = account_name.lower()
    for agency in agencies:
        if agency.display_name and agency.display_name.lower() in lowered:
            return agency.agency_id

    if "gst" in lowered or "hst" in lowered:
        for agency in agencies:
            if "revenue agency" in agency.display_name.lower():
                return agency.agency_id
    if "pst" in lowered:
        for agency in agencies:
            if "finance" in agency.display_name.lower():
                return agency.agency_id
    return None


def _last_day_of_month(dt: date) -> date:
    next_month = dt.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


def _is_month_end(dt: date) -> bool:
    return dt == _last_day_of_month(dt)


def _safe_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        return _last_day_of_month(date(year, month, 1))


def _add_months(dt: date, months: int) -> date:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    candidate = _safe_date(year, month, dt.day)
    if _is_month_end(dt):
        return _last_day_of_month(candidate)
    return candidate


def _infer_months_between(start: date | None, end: date | None) -> int | None:
    start = _to_date(start)  # type: ignore[assignment]
    end = _to_date(end)  # type: ignore[assignment]
    if start is None or end is None or end < start:
        return None
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    return months if months > 0 else None


def _expected_period_end_from_anchor(
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


def _is_payable_name(name: str) -> bool:
    return "payable" in name.lower()


def _is_suspense_name(name: str) -> bool:
    lowered = name.lower()
    return "suspense" in lowered or "suspence" in lowered


def _latest_filed_return_as_of(
    *,
    agency_returns: list[_TaxReturn],
    period_end: date,
) -> _TaxReturn | None:
    eligible = [
        ret
        for ret in agency_returns
        if ret.end_date is not None
        and ret.end_date <= period_end
        and ret.file_date is not None
        and ret.net_tax_amount_due is not None
        and not ret.upcoming_filing
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda ret: ret.end_date or date.min)


def _next_return_end_for_agency(
    *,
    agency_returns: list[_TaxReturn],
    current_end: date,
) -> date | None:
    future_ends = sorted(
        {
            ret.end_date
            for ret in agency_returns
            if ret.end_date is not None and ret.end_date > current_end
        }
    )
    return future_ends[0] if future_ends else None


def _payment_adjustment_for_suspense(
    *,
    payments: list[_TaxPayment],
    agency_id: str,
    return_end_date: date,
    period_end: date,
    next_return_end: date | None,
) -> tuple[Decimal, bool, int]:
    payments_have_agency_mapping = any(p.agency_id for p in payments)
    if not payments_have_agency_mapping:
        return Decimal("0"), False, 0

    adjustment = Decimal("0")
    count = 0
    for payment in payments:
        if payment.agency_id != agency_id:
            continue
        if payment.payment_amount is None or payment.payment_date is None:
            continue
        if payment.payment_date <= return_end_date:
            continue
        if payment.payment_date > period_end:
            continue
        if next_return_end is not None and payment.payment_date > next_return_end:
            continue

        amount_abs = abs(payment.payment_amount)
        if payment.refund:
            # Refund increases suspense outstanding.
            adjustment += amount_abs
        else:
            # Payment decreases suspense outstanding.
            adjustment -= amount_abs
        count += 1

    return adjustment, True, count


@register_rule
class BS_TAX_PAYABLE_AND_SUSPENSE_RECONCILE_TO_RETURN(Rule):
    rule_id = "BS-TAX-PAYABLE-AND-SUSPENSE-RECONCILE-TO-RETURN"
    rule_title = "Tax payable/suspense reconcile to most recent return"
    best_practices_reference = "Tax accounts"
    sources = ["QBO (Balance Sheet, TaxReturn, TaxPayment)"]
    config_model = TaxPayableAndSuspenseReconcileRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(
            self.rule_id, TaxPayableAndSuspenseReconcileRuleConfig
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

        agencies_item = ctx.evidence.first(cfg.tax_agencies_evidence_type)
        returns_item = ctx.evidence.first(cfg.tax_returns_evidence_type)
        payments_item = ctx.evidence.first(cfg.tax_payments_evidence_type)
        if agencies_item is None or returns_item is None or payments_item is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Missing tax agency/return/payment data; cannot reconcile tax balances.",
                evidence_used=[item for item in [agencies_item, returns_item, payments_item] if item],
                human_action="Provide TaxAgency, TaxReturn, and TaxPayment data from QBO.",
            )

        agencies = [
            _TaxAgency(
                agency_id=str(item.get("id") or ""),
                display_name=str(item.get("display_name") or ""),
            )
            for item in _iter_items(agencies_item.meta or {})
        ]
        returns = [
            _TaxReturn(
                agency_id=str(item.get("agency_id") or ""),
                start_date=_to_date(item.get("start_date")),
                end_date=_to_date(item.get("end_date")),
                file_date=_to_date(item.get("file_date")),
                net_tax_amount_due=_parse_decimal(item.get("net_tax_amount_due")),
                upcoming_filing=bool(item.get("upcoming_filing")),
            )
            for item in _iter_items(returns_item.meta or {})
        ]
        payments = [
            _TaxPayment(
                payment_date=_to_date(item.get("payment_date")),
                payment_amount=_parse_decimal(item.get("payment_amount")),
                refund=bool(item.get("refund")),
                agency_id=item.get("agency_id"),
            )
            for item in _iter_items(payments_item.meta or {})
        ]

        if not agencies or not returns:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=missing_status,
                severity=severity_for_status(missing_status),
                summary="Tax agency/return data is empty; cannot reconcile tax balances.",
                evidence_used=[agencies_item, returns_item, payments_item],
                human_action="Confirm TaxAgency and TaxReturn exports contain data.",
            )

        scope_accounts = [
            acct
            for acct in ctx.balance_sheet.accounts
            if acct.account_ref
            and not acct.account_ref.startswith("report::")
            and acct.name
            and _name_matches(acct.name, cfg.account_name_patterns)
        ]
        if not scope_accounts:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=severity_for_status(RuleStatus.NOT_APPLICABLE),
                summary="No tax payable/suspense accounts found on Balance Sheet.",
            )

        unmatched_accounts = []
        accounts_by_agency: dict[str, list] = {}
        for acct in scope_accounts:
            agency_id = _infer_agency_for_account(acct.name, agencies)
            if not agency_id:
                unmatched_accounts.append(acct)
                continue
            accounts_by_agency.setdefault(agency_id, []).append(acct)

        details: list[RuleResultDetail] = []
        overall_status = RuleStatus.PASS
        status_rank = {
            RuleStatus.PASS: 0,
            RuleStatus.NOT_APPLICABLE: 1,
            RuleStatus.NEEDS_REVIEW: 2,
            RuleStatus.WARN: 3,
            RuleStatus.FAIL: 4,
        }

        if unmatched_accounts:
            if status_rank[missing_status] > status_rank[overall_status]:
                overall_status = missing_status
            details.extend(
                [
                    RuleResultDetail(
                        key=acct.account_ref,
                        message="Tax account could not be mapped to a tax agency.",
                        values={
                            "account_name": acct.name,
                            "balance": str(acct.balance),
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                    for acct in unmatched_accounts
                ]
            )

        for agency_id, accounts in accounts_by_agency.items():
            agency = next((a for a in agencies if a.agency_id == agency_id), None)
            agency_name = agency.display_name if agency else agency_id
            agency_returns = [r for r in returns if r.agency_id == agency_id]
            target_return = _latest_filed_return_as_of(
                agency_returns=agency_returns,
                period_end=ctx.period_end,
            )
            if target_return is None:
                if status_rank[missing_status] > status_rank[overall_status]:
                    overall_status = missing_status
                details.append(
                    RuleResultDetail(
                        key=agency_id,
                        message="No filed tax return found for agency on or before period end.",
                        values={
                            "agency_name": agency_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                )
                continue

            if target_return.net_tax_amount_due is None or target_return.end_date is None:
                if status_rank[missing_status] > status_rank[overall_status]:
                    overall_status = missing_status
                details.append(
                    RuleResultDetail(
                        key=agency_id,
                        message="Latest filed return is missing required net due or end date fields.",
                        values={
                            "agency_name": agency_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": missing_status.value,
                        },
                    )
                )
                continue

            payable_only = sum(
                acct.balance for acct in accounts if _is_payable_name(acct.name or "")
            )
            suspense_only = sum(
                acct.balance for acct in accounts if _is_suspense_name(acct.name or "")
            )

            next_return_end = _next_return_end_for_agency(
                agency_returns=agency_returns,
                current_end=target_return.end_date,
            )
            payment_adjustment, payments_mapped_to_agency, payment_count = (
                _payment_adjustment_for_suspense(
                    payments=payments,
                    agency_id=agency_id,
                    return_end_date=target_return.end_date,
                    period_end=ctx.period_end,
                    next_return_end=next_return_end,
                )
            )
            expected_suspense = target_return.net_tax_amount_due + payment_adjustment

            payable_status = RuleStatus.PASS if payable_only == 0 else RuleStatus.FAIL
            suspense_difference = abs(suspense_only - expected_suspense)
            suspense_status = (
                RuleStatus.PASS if suspense_difference == 0 else RuleStatus(cfg.delinquent_status.value)
            )
            core_status = (
                payable_status
                if status_rank[payable_status] >= status_rank[suspense_status]
                else suspense_status
            )

            if status_rank[core_status] > status_rank[overall_status]:
                overall_status = core_status

            details.append(
                RuleResultDetail(
                    key=agency_id,
                    message=(
                        "Tax payable must be zero and suspense must tie to the most recent filed return "
                        "plus payment/refund offsets."
                    ),
                    values={
                        "agency_name": agency_name,
                        "period_end": ctx.period_end.isoformat(),
                        "expected_period_end": target_return.end_date.isoformat(),
                        "next_expected_period_end": next_return_end.isoformat()
                        if next_return_end is not None
                        else None,
                        "return_start_date": target_return.start_date.isoformat()
                        if target_return.start_date
                        else None,
                        "return_end_date": target_return.end_date.isoformat()
                        if target_return.end_date
                        else None,
                        "return_file_date": target_return.file_date.isoformat()
                        if target_return.file_date
                        else None,
                        "return_net_tax_due": str(target_return.net_tax_amount_due),
                        "payment_adjustment_to_suspense": str(payment_adjustment),
                        "payments_mapped_to_agency": payments_mapped_to_agency,
                        "payments_applied_count": payment_count,
                        "expected_suspense": str(expected_suspense),
                        "suspense_difference": str(suspense_difference),
                        "payable_only": str(payable_only),
                        "suspense_only": str(suspense_only),
                        "payable_must_be_zero": True,
                        "payable_status": payable_status.value,
                        "suspense_status": suspense_status.value,
                        "status": core_status.value,
                    },
                )
            )

        summary = (
            f"Tax payable is zero and suspense ties to the most recent filed return as of {ctx.period_end.isoformat()}."
            if overall_status == RuleStatus.PASS
            else "Tax payable must be zero and suspense must reconcile to the most recent filed return."
        )

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=overall_status,
            severity=severity_for_status(overall_status),
            summary=summary,
            details=details,
            evidence_used=[agencies_item, returns_item, payments_item],
            human_action=(
                "Move any tax balance out of payable (payable must be zero) and reconcile suspense to the latest "
                "filed return plus payment/refund offsets for that filing period."
                if overall_status != RuleStatus.PASS
                else None
            ),
        )
