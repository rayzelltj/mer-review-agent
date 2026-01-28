from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class RuleStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def severity_for_status(status: "RuleStatus") -> Severity:
    # Fixed mapping (firm policy): status already encodes urgency; severity is a stable derivative for sorting/triage.
    return {
        RuleStatus.PASS: Severity.INFO,
        RuleStatus.WARN: Severity.LOW,
        RuleStatus.FAIL: Severity.HIGH,
        RuleStatus.NEEDS_REVIEW: Severity.MEDIUM,
        RuleStatus.NOT_APPLICABLE: Severity.INFO,
    }[status]


class MissingDataPolicy(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AccountBalance(BaseModel):
    account_ref: str
    name: str
    type: str = ""
    subtype: str = ""
    balance: Decimal


class BalanceSheetSnapshot(BaseModel):
    as_of_date: date
    currency: str = "USD"
    accounts: List[AccountBalance] = Field(default_factory=list)


class ProfitAndLossSnapshot(BaseModel):
    period_start: date
    period_end: date
    currency: str = "USD"
    totals: Dict[str, Decimal] = Field(default_factory=dict)

    def get_total(self, key: str) -> Optional[Decimal]:
        return self.totals.get(key)


class EvidenceItem(BaseModel):
    evidence_type: str
    source: str
    as_of_date: Optional[date] = None
    statement_end_date: Optional[date] = None
    amount: Optional[Decimal] = None
    uri: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class EvidenceBundle(BaseModel):
    items: List[EvidenceItem] = Field(default_factory=list)

    def first(self, evidence_type: str) -> Optional[EvidenceItem]:
        for item in self.items:
            if item.evidence_type == evidence_type:
                return item
        return None


class ReconciliationSnapshot(BaseModel):
    account_ref: str
    account_name: str = ""

    statement_end_date: Optional[date] = None
    statement_ending_balance: Optional[Decimal] = None

    book_balance_as_of_statement_end: Optional[Decimal] = None
    book_balance_as_of_period_end: Optional[Decimal] = None

    source: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)


class RuleResultDetail(BaseModel):
    key: str
    message: str
    values: Dict[str, Any] = Field(default_factory=dict)


class RuleResult(BaseModel):
    rule_id: str
    rule_title: str
    best_practices_reference: str = ""
    sources: List[str] = Field(default_factory=list)

    status: RuleStatus
    severity: Severity = Severity.MEDIUM
    summary: str = ""

    details: List[RuleResultDetail] = Field(default_factory=list)
    evidence_used: List[EvidenceItem] = Field(default_factory=list)
    human_action: Optional[str] = None


class RuleRunReport(BaseModel):
    run_id: str
    generated_at: datetime
    period_end: date

    results: List[RuleResult] = Field(default_factory=list)
    totals: Dict[RuleStatus, int] = Field(default_factory=dict)


@dataclass(frozen=True)
class StatusOrdering:
    order: Dict[RuleStatus, int]

    @classmethod
    def default(cls) -> "StatusOrdering":
        # Higher wins.
        return cls(
            order={
                RuleStatus.FAIL: 50,
                RuleStatus.NEEDS_REVIEW: 40,
                RuleStatus.WARN: 30,
                RuleStatus.PASS: 20,
                RuleStatus.NOT_APPLICABLE: 10,
            }
        )

    def worst(self, statuses: List[RuleStatus]) -> RuleStatus:
        if not statuses:
            return RuleStatus.NOT_APPLICABLE
        return max(statuses, key=lambda s: self.order.get(s, 0))
