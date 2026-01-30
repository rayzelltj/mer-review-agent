from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from common.rules_engine.models import EvidenceBundle, EvidenceItem


def evidence_bundle_from_manifest(
    manifest: dict[str, Any],
    *,
    source_default: str = "fixture",
) -> EvidenceBundle:
    """
    Build an EvidenceBundle from a JSON manifest.

    Expected shape:
      {
        "evidence": [
          {
            "evidence_type": "...",
            "amount": "123.45",
            "as_of_date": "YYYY-MM-DD",
            "statement_end_date": "YYYY-MM-DD",
            "uri": "fixture://...",
            "source": "fixture",
            "meta": { ... }
          }
        ]
      }

    Notes:
    - evidence_type is required
    - amount/date fields are optional and parsed if present
    """
    items_raw = _select_items(manifest)
    items: list[EvidenceItem] = []
    for entry in items_raw:
        if not isinstance(entry, dict):
            raise ValueError("Evidence manifest entries must be objects.")
        evidence_type = entry.get("evidence_type")
        if not evidence_type:
            raise ValueError("Evidence entry missing required field: evidence_type")

        items.append(
            EvidenceItem(
                evidence_type=str(evidence_type),
                source=str(entry.get("source") or source_default),
                as_of_date=_parse_date(entry.get("as_of_date")),
                statement_end_date=_parse_date(entry.get("statement_end_date")),
                amount=_parse_decimal(entry.get("amount")),
                uri=entry.get("uri"),
                meta=dict(entry.get("meta") or {}),
            )
        )
    return EvidenceBundle(items=items)


def _select_items(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    if "evidence" in manifest:
        return manifest.get("evidence") or []
    if "items" in manifest:
        return manifest.get("items") or []
    return []


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))
