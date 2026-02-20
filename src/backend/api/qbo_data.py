from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from auth.auth_utils import get_authenticated_user_details, is_easyauth_enabled
from common.client_id import load_client_aliases, resolve_client_id, suggest_client_ids
from connectors.qbo.accounts import fetch_accounts_all
from connectors.qbo.aging import (
    fetch_aged_payables_detail,
    fetch_aged_payables_summary,
    fetch_aged_receivables_detail,
    fetch_aged_receivables_summary,
)
from connectors.qbo.client import QBOHttpError, qbo_get
from connectors.qbo.client_store import get_qbo_client_record, list_qbo_client_ids
from connectors.qbo.config import QBOConfig, build_qbo_config, get_client_store_mode
from connectors.qbo.tax import (
    fetch_tax_agencies_payload,
    fetch_tax_payments_payload,
    fetch_tax_returns_payload,
    tax_agencies_from_payload,
    tax_payments_from_payload,
    tax_returns_from_payload,
)

router = APIRouter(prefix="/api/qbo/data", tags=["qbo-data"])

_FILTER_PARAM_MAP = {
    "class": "class",
    "location": "department",
    "department": "department",
    "customer": "customer",
    "project": "customer",
    "vendor": "vendor",
    "tag": "tag",
    "account": "account",
}

_TRANSACTION_ENTITY_CANDIDATES = (
    "Invoice",
    "Bill",
    "JournalEntry",
    "SalesReceipt",
    "Payment",
    "BillPayment",
    "CreditMemo",
    "VendorCredit",
    "Check",
    "Deposit",
    "Transfer",
    "Purchase",
    "RefundReceipt",
)

_PAYROLL_NAME_HINTS = (
    "payroll",
    "wages payable",
    "salary payable",
    "source deduction",
    "cpp payable",
    "ei payable",
    "income tax payable",
    "withholding",
)


def _authenticated_user_id(http_request: Request) -> str | None:
    user = get_authenticated_user_details(request_headers=http_request.headers)
    user_id = str(user.get("user_principal_id") or "").strip()
    if is_easyauth_enabled() and not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id or None


class StatementRequest(BaseModel):
    client_id: str | None = None
    basis: str = Field(default="Accrual")
    summarize_by: str | None = None
    filters: dict[str, Any] | None = None


class DateRangeStatementRequest(StatementRequest):
    start_date: date
    end_date: date


class AsOfStatementRequest(StatementRequest):
    as_of_date: date


class GLDetailRequest(DateRangeStatementRequest):
    account_id: str | None = None
    account_name: str | None = None
    account: str | None = None
    class_name: str | None = None
    location: str | None = None
    customer: str | None = None
    vendor: str | None = None
    min_amount: float | None = None


class TransactionsByAccountRequest(BaseModel):
    client_id: str | None = None
    account_id: str
    start_date: date
    end_date: date
    basis: str = Field(default="Accrual")
    include_splits: bool = True
    filters: dict[str, Any] | None = None


class TransactionRequest(BaseModel):
    transaction_id: str
    client_id: str | None = None


class ListAccountsRequest(BaseModel):
    client_id: str | None = None
    include_inactive: bool = True


class AgingRequest(BaseModel):
    client_id: str | None = None
    as_of_date: date


class OpenDocumentsRequest(BaseModel):
    client_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class BankReconciliationStatusRequest(BaseModel):
    client_id: str | None = None
    bank_account_id: str
    as_of_date: date | None = None


class SalesTaxLiabilityRequest(BaseModel):
    client_id: str | None = None
    start_date: date
    end_date: date
    basis: str = Field(default="Accrual")


class SalesTaxReturnsRequest(BaseModel):
    client_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class PayrollLiabilitiesRequest(BaseModel):
    client_id: str | None = None
    as_of_date: date | None = None


@router.post("/profit-and-loss")
def qbo_get_profit_and_loss(
    request: DateRangeStatementRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    params = _build_report_params(
        start_date=request.start_date,
        end_date=request.end_date,
        basis=request.basis,
        summarize_by=request.summarize_by,
        filters=request.filters,
    )
    payload = _fetch_report(config, "ProfitAndLoss", params=params)
    return _response_envelope(
        tool_name="qbo_get_profit_and_loss",
        client_id=resolved_client_id,
        store_mode=store_mode,
        config=config,
        params=params,
        payload=payload,
    )


@router.post("/balance-sheet")
def qbo_get_balance_sheet(
    request: AsOfStatementRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    params = _build_report_params(
        as_of_date=request.as_of_date,
        basis=request.basis,
        summarize_by=request.summarize_by,
        filters=request.filters,
    )
    payload = _fetch_report(config, "BalanceSheet", params=params)
    return _response_envelope(
        tool_name="qbo_get_balance_sheet",
        client_id=resolved_client_id,
        store_mode=store_mode,
        config=config,
        params=params,
        payload=payload,
    )


@router.post("/cash-flow")
def qbo_get_cash_flow(
    request: DateRangeStatementRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    params = _build_report_params(
        start_date=request.start_date,
        end_date=request.end_date,
        basis=request.basis,
        filters=request.filters,
    )
    payload = _fetch_report(config, "StatementOfCashFlows", params=params)
    return _response_envelope(
        tool_name="qbo_get_cash_flow",
        client_id=resolved_client_id,
        store_mode=store_mode,
        config=config,
        params=params,
        payload=payload,
    )


@router.post("/trial-balance")
def qbo_get_trial_balance(
    request: DateRangeStatementRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    params = _build_report_params(
        start_date=request.start_date,
        end_date=request.end_date,
        basis=request.basis,
        filters=request.filters,
    )
    payload = _fetch_report(config, "TrialBalance", params=params)
    return _response_envelope(
        tool_name="qbo_get_trial_balance",
        client_id=resolved_client_id,
        store_mode=store_mode,
        config=config,
        params=params,
        payload=payload,
    )


@router.post("/gl-detail")
def qbo_get_gl_detail(request: GLDetailRequest, http_request: Request) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    filters = dict(request.filters or {})
    if request.class_name:
        filters.setdefault("class", request.class_name)
    if request.location:
        filters.setdefault("location", request.location)
    if request.customer:
        filters.setdefault("customer", request.customer)
    if request.vendor:
        filters.setdefault("vendor", request.vendor)
    if request.account or request.account_id or request.account_name:
        filters.setdefault("account", request.account or request.account_id or request.account_name)

    params = _build_report_params(
        start_date=request.start_date,
        end_date=request.end_date,
        basis=request.basis,
        filters=filters,
    )
    payload = _fetch_report(config, "GeneralLedger", params=params)
    if request.min_amount is not None and request.min_amount > 0:
        payload = _filter_report_payload_by_min_amount(payload, Decimal(str(request.min_amount)))
    return _response_envelope(
        tool_name="qbo_get_gl_detail",
        client_id=resolved_client_id,
        store_mode=store_mode,
        config=config,
        params=params,
        payload=payload,
        extra={
            "requested_min_amount": request.min_amount,
        },
    )


@router.post("/transactions/by-account")
def qbo_get_transactions_by_account(
    request: TransactionsByAccountRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    params = _build_report_params(
        start_date=request.start_date,
        end_date=request.end_date,
        basis=request.basis,
        filters=request.filters,
    )
    params["account"] = request.account_id
    # QBO report behavior differs by realm/version; avoid forcing this param unless disabling splits.
    if not request.include_splits:
        params["include_split_detail"] = "false"

    report_name = "TransactionListByAccount"
    try:
        payload = _fetch_report(config, report_name, params=params)
    except HTTPException as exc:
        fallback_params = dict(params)
        fallback_params.pop("include_split_detail", None)
        fallback_report_name = "TransactionList"
        if exc.status_code != 502:
            raise
        try:
            payload = _fetch_report(config, fallback_report_name, params=fallback_params)
            report_name = fallback_report_name
            params = fallback_params
        except HTTPException:
            raise exc

    return _response_envelope(
        tool_name="qbo_get_transactions_by_account",
        client_id=resolved_client_id,
        store_mode=store_mode,
        config=config,
        params=params,
        payload=payload,
        extra={"account_id": request.account_id, "report_name": report_name},
    )


@router.post("/transaction")
def qbo_get_transaction(request: TransactionRequest, http_request: Request) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    found_entity, transaction_payload = _fetch_transaction_by_id(
        config=config,
        transaction_id=request.transaction_id,
    )
    return {
        "tool": "qbo_get_transaction",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "transaction_id": request.transaction_id,
        "entity_type": found_entity,
        "transaction": transaction_payload,
    }


@router.post("/accounts")
def qbo_list_accounts(request: ListAccountsRequest, http_request: Request) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    payload = fetch_accounts_all(config, max_results=1000)
    accounts = _query_items(payload, "Account")
    if not request.include_inactive:
        accounts = [item for item in accounts if item.get("Active") is not False]
    return {
        "tool": "qbo_list_accounts",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "accounts_count": len(accounts),
        "accounts": accounts,
    }


@router.post("/ar-aging")
def qbo_get_ar_aging(request: AgingRequest, http_request: Request) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    as_of_date = request.as_of_date.isoformat()
    summary = fetch_aged_receivables_summary(config, as_of_date=as_of_date)
    detail = fetch_aged_receivables_detail(config, as_of_date=as_of_date)
    return {
        "tool": "qbo_get_ar_aging",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "as_of_date": as_of_date,
        "summary": summary,
        "detail": detail,
    }


@router.post("/ap-aging")
def qbo_get_ap_aging(request: AgingRequest, http_request: Request) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    as_of_date = request.as_of_date.isoformat()
    summary = fetch_aged_payables_summary(config, as_of_date=as_of_date)
    detail = fetch_aged_payables_detail(config, as_of_date=as_of_date)
    return {
        "tool": "qbo_get_ap_aging",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "as_of_date": as_of_date,
        "summary": summary,
        "detail": detail,
    }


@router.post("/open-invoices")
def qbo_get_open_invoices(
    request: OpenDocumentsRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    where = ["Balance > '0'"]
    if request.start_date:
        where.append(f"TxnDate >= '{request.start_date.isoformat()}'")
    if request.end_date:
        where.append(f"TxnDate <= '{request.end_date.isoformat()}'")
    invoices = _query_all(config=config, entity="Invoice", where_clauses=where)
    return {
        "tool": "qbo_get_open_invoices",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "count": len(invoices),
        "transactions": invoices,
    }


@router.post("/open-bills")
def qbo_get_open_bills(
    request: OpenDocumentsRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    where = ["Balance > '0'"]
    if request.start_date:
        where.append(f"TxnDate >= '{request.start_date.isoformat()}'")
    if request.end_date:
        where.append(f"TxnDate <= '{request.end_date.isoformat()}'")
    bills = _query_all(config=config, entity="Bill", where_clauses=where)
    return {
        "tool": "qbo_get_open_bills",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "count": len(bills),
        "transactions": bills,
    }


@router.post("/bank-reconciliation-status")
def qbo_get_bank_reconciliation_status(
    request: BankReconciliationStatusRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    account_payload = _query_single(
        config=config,
        entity="Account",
        where_clauses=[f"Id = '{_qbo_quote(request.bank_account_id)}'"],
    )
    account = account_payload or {}
    last_reconciled = account.get("LastReconciliationDate") or account.get("LastReconcileDate")
    as_of_date = request.as_of_date.isoformat() if request.as_of_date else None
    status = "unknown"
    if last_reconciled and as_of_date and str(last_reconciled) >= as_of_date:
        status = "reconciled_through_as_of"

    return {
        "tool": "qbo_get_bank_reconciliation_status",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "bank_account_id": request.bank_account_id,
        "as_of_date": as_of_date,
        "status": status,
        "last_reconciliation_date": last_reconciled,
        "supported": bool(last_reconciled),
        "note": (
            "QBO API may not expose reconciliation state for all ledgers. "
            "If supported is false, use bank reconciliation reports/evidence."
        ),
        "account": account_payload,
    }


@router.post("/sales-tax-returns")
def qbo_get_sales_tax_returns(
    request: SalesTaxReturnsRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    start_date = request.start_date.isoformat() if request.start_date else None
    end_date = request.end_date.isoformat() if request.end_date else None

    agencies_payload = fetch_tax_agencies_payload(config)
    returns_payload = fetch_tax_returns_payload(config, start_date=start_date, end_date=end_date)
    payments_payload = fetch_tax_payments_payload(config, start_date=start_date, end_date=end_date)

    agencies = tax_agencies_from_payload(agencies_payload)
    returns = tax_returns_from_payload(returns_payload)
    payments = tax_payments_from_payload(payments_payload)
    return {
        "tool": "qbo_get_sales_tax_returns",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "start_date": start_date,
        "end_date": end_date,
        "agencies_count": len(agencies),
        "returns_count": len(returns),
        "payments_count": len(payments),
        "agencies": agencies,
        "returns": returns,
        "payments": payments,
    }


@router.post("/sales-tax-liability")
def qbo_get_sales_tax_liability(
    request: SalesTaxLiabilityRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    start_date = request.start_date.isoformat()
    end_date = request.end_date.isoformat()
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "accounting_method": _normalize_basis(request.basis),
    }
    try:
        payload = _fetch_report(config, "TaxSummary", params=params)
        return _response_envelope(
            tool_name="qbo_get_sales_tax_liability",
            client_id=resolved_client_id,
            store_mode=store_mode,
            config=config,
            params=params,
            payload=payload,
        )
    except HTTPException:
        raise
    except Exception:
        # Fallback for realms where TaxSummary report is unavailable.
        returns_payload = fetch_tax_returns_payload(config, start_date=start_date, end_date=end_date)
        returns = tax_returns_from_payload(returns_payload)
        net_due_total = Decimal("0")
        for item in returns:
            net_due_total += _to_decimal(item.get("NetTaxAmountDue"))
        return {
            "tool": "qbo_get_sales_tax_liability",
            "client_id": resolved_client_id,
            "store_mode": store_mode,
            "realm_id": config.realm_id,
            "start_date": start_date,
            "end_date": end_date,
            "report_available": False,
            "net_tax_amount_due_total": str(net_due_total),
            "returns_count": len(returns),
            "returns": returns,
        }


@router.post("/payroll-liabilities")
def qbo_get_payroll_liabilities(
    request: PayrollLiabilitiesRequest,
    http_request: Request,
) -> dict[str, Any]:
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id, config, store_mode = _resolve_client_and_config(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    liabilities = _query_all(
        config=config,
        entity="Account",
        where_clauses=["AccountType = 'Other Current Liability'"],
    )
    payroll_accounts = [
        item
        for item in liabilities
        if _looks_like_payroll_account(item.get("Name"))
    ]
    as_of_date = request.as_of_date.isoformat() if request.as_of_date else None
    if as_of_date:
        bs_payload = _fetch_report(
            config,
            "BalanceSheet",
            params={"end_date": as_of_date, "accounting_method": "Accrual"},
        )
    else:
        bs_payload = None
    return {
        "tool": "qbo_get_payroll_liabilities",
        "client_id": resolved_client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "as_of_date": as_of_date,
        "payroll_liability_accounts_count": len(payroll_accounts),
        "accounts": payroll_accounts,
        "balance_sheet_reference": bs_payload,
        "note": (
            "Payroll APIs vary by subscription/region. "
            "Use payroll liability accounts plus supporting filings for review."
        ),
    }


def _response_envelope(
    *,
    tool_name: str,
    client_id: str,
    store_mode: str,
    config: QBOConfig,
    params: dict[str, Any],
    payload: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = {
        "tool": tool_name,
        "client_id": client_id,
        "store_mode": store_mode,
        "realm_id": config.realm_id,
        "params": params,
        "report": payload,
    }
    if extra:
        envelope.update(extra)
    return envelope


def _resolve_client_and_config(
    client_id: str | None,
    *,
    user_principal_id: str | None,
) -> tuple[str, QBOConfig, str]:
    store_mode = get_client_store_mode()
    aliases = load_client_aliases()
    if store_mode == "cosmos":
        known_ids: list[str] = []
        try:
            known_ids = list_qbo_client_ids(
                limit=200,
                user_principal_id=user_principal_id,
            )
        except Exception:
            known_ids = []

        selected_client = (client_id or "").strip()
        if not selected_client:
            if len(known_ids) == 1:
                selected_client = known_ids[0]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="client_id is required when multiple QBO clients exist.",
                )

        resolved_client = resolve_client_id(selected_client, known_ids, aliases)
        record = get_qbo_client_record(
            resolved_client,
            user_principal_id=user_principal_id,
        )
        if record is None:
            suggestions: list[str] = []
            try:
                suggestions = suggest_client_ids(resolved_client, known_ids)
            except Exception:
                suggestions = []
            raise HTTPException(
                status_code=404,
                detail={
                    "message": f"QBO client '{selected_client}' not found.",
                    "resolved_client_id": resolved_client,
                    "suggested_client_ids": suggestions,
                },
            )

        realm_id = str(record.get("realm_id") or "").strip()
        refresh_token = str(record.get("refresh_token") or "").strip()
        if not realm_id or not refresh_token:
            raise HTTPException(
                status_code=409,
                detail=f"QBO connection incomplete for client '{resolved_client}'.",
            )

        config = build_qbo_config(
            realm_id=realm_id,
            access_token="",
            refresh_token=refresh_token,
            token_expires_at="",
            client_record_id=resolved_client,
            user_principal_id=user_principal_id,
        )
        return resolved_client, config, store_mode

    try:
        config = build_qbo_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to load QBO config: {exc}") from exc

    resolved = (client_id or "").strip() or "default"
    return resolved, config, store_mode


def _build_report_params(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    as_of_date: date | None = None,
    basis: str = "Accrual",
    summarize_by: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"accounting_method": _normalize_basis(basis)}
    if start_date:
        params["start_date"] = start_date.isoformat()
    if end_date:
        params["end_date"] = end_date.isoformat()
    if as_of_date:
        params["end_date"] = as_of_date.isoformat()
    if summarize_by:
        params["summarize_column_by"] = summarize_by
    _apply_filters(params, filters)
    return params


def _normalize_basis(value: str) -> str:
    lowered = (value or "Accrual").strip().lower()
    if lowered in {"accrual", "accruals"}:
        return "Accrual"
    if lowered == "cash":
        return "Cash"
    raise HTTPException(status_code=400, detail="basis must be 'Accrual' or 'Cash'.")


def _apply_filters(params: dict[str, Any], filters: dict[str, Any] | None) -> None:
    if not filters:
        return
    for raw_key, raw_value in filters.items():
        key = _FILTER_PARAM_MAP.get(str(raw_key or "").strip().lower())
        if not key or raw_value in (None, "", []):
            continue
        params[key] = _stringify_filter_value(raw_value)


def _stringify_filter_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(parts)
    return str(value).strip()


def _fetch_report(config: QBOConfig, report_name: str, *, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return qbo_get(
            config,
            f"/v3/company/{config.realm_id}/reports/{report_name}",
            params=params,
        )
    except QBOHttpError as exc:
        detail = f"QBO report call failed ({report_name}): {exc}"
        if exc.body:
            body_text = exc.body.strip()
            if body_text:
                max_len = 1200
                clipped = body_text[:max_len]
                if len(body_text) > max_len:
                    clipped += "...<truncated>"
                detail = f"{detail} | response_body={clipped}"
        raise HTTPException(
            status_code=502,
            detail=detail,
        ) from exc


def _query_items(payload: dict[str, Any], entity: str) -> list[dict[str, Any]]:
    query_response = payload.get("QueryResponse") if isinstance(payload, dict) else None
    if not isinstance(query_response, dict):
        return []
    items = query_response.get(entity)
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if isinstance(items, dict):
        return [items]
    return []


def _query_single(
    *,
    config: QBOConfig,
    entity: str,
    where_clauses: Iterable[str],
) -> dict[str, Any] | None:
    results = _query_all(
        config=config,
        entity=entity,
        where_clauses=where_clauses,
        max_results=1,
    )
    if not results:
        return None
    return results[0]


def _query_all(
    *,
    config: QBOConfig,
    entity: str,
    where_clauses: Iterable[str],
    max_results: int = 1000,
) -> list[dict[str, Any]]:
    if max_results <= 0:
        raise ValueError("max_results must be greater than zero")

    clauses = [clause.strip() for clause in where_clauses if clause and clause.strip()]
    where = f" where {' and '.join(clauses)}" if clauses else ""
    items: list[dict[str, Any]] = []
    start_position = 1

    while True:
        query = (
            f"select * from {entity}{where} "
            f"startposition {start_position} maxresults {max_results}"
        )
        payload = qbo_get(
            config,
            f"/v3/company/{config.realm_id}/query",
            params={"query": query},
        )
        batch = _query_items(payload, entity)
        items.extend(batch)
        if len(batch) < max_results:
            break
        start_position += max_results
    return items


def _fetch_transaction_by_id(*, config: QBOConfig, transaction_id: str) -> tuple[str, dict[str, Any]]:
    txn_id = (transaction_id or "").strip()
    if not txn_id:
        raise HTTPException(status_code=400, detail="transaction_id is required")

    quoted_id = _qbo_quote(txn_id)
    for entity in _TRANSACTION_ENTITY_CANDIDATES:
        try:
            result = _query_single(
                config=config,
                entity=entity,
                where_clauses=[f"Id = '{quoted_id}'"],
            )
        except QBOHttpError:
            continue
        if result is not None:
            return entity, result

    raise HTTPException(
        status_code=404,
        detail=f"Transaction '{txn_id}' was not found across supported entity types.",
    )


def _filter_report_payload_by_min_amount(payload: dict[str, Any], min_amount: Decimal) -> dict[str, Any]:
    if min_amount <= 0:
        return payload
    filtered = deepcopy(payload)
    rows = filtered.get("Rows")
    if not isinstance(rows, dict):
        return filtered
    original_rows = rows.get("Row")
    if not isinstance(original_rows, list):
        return filtered
    rows["Row"] = _filter_rows_recursive(original_rows, min_amount)
    return filtered


def _filter_rows_recursive(rows: list[dict[str, Any]], min_amount: Decimal) -> list[dict[str, Any]]:
    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        keep_current = _row_has_amount(row, min_amount)
        nested = row.get("Rows")
        filtered_nested_rows: list[dict[str, Any]] = []
        if isinstance(nested, dict):
            nested_rows = nested.get("Row")
            if isinstance(nested_rows, list):
                filtered_nested_rows = _filter_rows_recursive(nested_rows, min_amount)
                nested["Row"] = filtered_nested_rows
        if keep_current or filtered_nested_rows:
            filtered_rows.append(row)
    return filtered_rows


def _row_has_amount(row: dict[str, Any], min_amount: Decimal) -> bool:
    col_data = row.get("ColData")
    if not isinstance(col_data, list):
        return False
    for column in col_data:
        if not isinstance(column, dict):
            continue
        value = column.get("value")
        amount = _to_decimal(value)
        if amount.copy_abs() >= min_amount:
            return True
    return False


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    text = str(value).strip()
    if not text:
        return Decimal("0")
    cleaned = (
        text.replace(",", "")
        .replace("$", "")
        .replace("(", "-")
        .replace(")", "")
    )
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def _qbo_quote(value: str) -> str:
    return str(value or "").replace("'", "''")


def _looks_like_payroll_account(name: str | None) -> bool:
    lowered = str(name or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in _PAYROLL_NAME_HINTS)
