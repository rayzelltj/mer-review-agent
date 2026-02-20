from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from common.rules_engine.models import RuleResult


class MissingEvidenceRequest(BaseModel):
    evidence_type: str
    description: str
    suggested_source: Literal["Drive", "QBO"]
    rule_id: str | None = None
    rule_title: str | None = None
    required_document: str | None = None
    adapter_hint: str | None = None


class BalanceSheetRunRecord(BaseModel):
    id: str
    session_id: str
    data_type: Literal["balance_sheet_run"] = "balance_sheet_run"
    user_principal_id: str | None = None
    client_id: str
    period_end: date
    status: Literal["queued", "running", "raw", "fetched", "done", "failed"]
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    findings: List[RuleResult] = Field(default_factory=list)
    totals: Dict[str, int] = Field(default_factory=dict)
    run_report: Optional[Dict[str, Any]] = None
    balance_sheet_view: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    hitl_requests: List[MissingEvidenceRequest] = Field(default_factory=list)
    snapshot_keys: Dict[str, str] = Field(default_factory=dict)
    artifact_keys: Dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None
