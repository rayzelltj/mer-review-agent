"""
Bank statement parser registry.

Usage
-----
::

    from adapters.bank_statements import detect_and_parse, parse_with_parser

    # Auto-detect institution and return a single EvidenceItem:
    evidence_item = detect_and_parse(pdf_bytes, account_ref="67", account_id="67")

    # Force a specific parser (bypasses auto-detection):
    evidence_item = parse_with_parser("paypal", pdf_bytes, account_ref="67",
                                       extra_meta={"currency": "CAD"})

    # Get one EvidenceItem per currency section in a multi-currency PDF:
    items = detect_and_parse_all(pdf_bytes)
"""

from __future__ import annotations

from typing import Any

from common.rules_engine.models import EvidenceItem

from .base import BankStatementParseError, BankStatementParser
from .pdf_utils import extract_pages

# ── Ordered list of registered parsers (most-specific first). ────────────────
# Populated at import time via ``_register()``.
_PARSERS: list[BankStatementParser] = []
_PARSERS_LOADED = False


def _register(parser: BankStatementParser) -> None:
    """Add *parser* to the global registry."""
    _PARSERS.append(parser)


def _ensure_parsers_loaded() -> None:
    """Import parser modules so their ``_register()`` calls execute."""
    global _PARSERS_LOADED
    if _PARSERS_LOADED:
        return
    from .parsers import paypal, rbc_visa  # noqa: F401  side-effects only

    _PARSERS_LOADED = True


# ── Public API ────────────────────────────────────────────────────────────────


def detect_and_parse(
    pdf_bytes: bytes,
    *,
    account_ref: str | None = None,
    account_id: str | None = None,
    source: str = "bank_statement_pdf",
    uri: str | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> EvidenceItem:
    """Auto-detect institution, parse, and return one ``EvidenceItem``.

    For multi-currency PDFs (e.g. PayPal) a *currency* key in *extra_meta*
    selects which section to return; otherwise the first/primary section is used.

    Raises:
        BankStatementParseError: if no parser recognises the document.
        ImportError: if no PDF library (pdfplumber / pypdf) is installed.
    """
    _ensure_parsers_loaded()
    pages = extract_pages(pdf_bytes)

    for parser in _PARSERS:
        if not parser.can_parse(pages):
            continue
        # For multi-currency parsers let ``parse_all`` run and apply currency filter.
        all_results = parser.parse_all(pages)
        if not all_results:
            continue
        currency_filter = (extra_meta or {}).get("currency")
        if currency_filter:
            match = next(
                (r for r in all_results if r.currency == currency_filter),
                None,
            )
            result = match or all_results[0]
        else:
            result = all_results[0]
        return result.to_evidence_item(
            account_ref=account_ref,
            account_id=account_id,
            source=source,
            uri=uri,
            extra_meta=extra_meta,
        )

    # ── LLM fallback ─────────────────────────────────────────────────────────
    # No deterministic parser matched.  Attempt LLM-structured extraction so
    # that unknown formats still produce a result (with confidence < 1.0).
    try:
        from .llm_extractor import llm_extract_statement

        result = llm_extract_statement(pages)
        return result.to_evidence_item(
            account_ref=account_ref,
            account_id=account_id,
            source=source,
            uri=uri,
            extra_meta=extra_meta,
        )
    except Exception as llm_exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "LLM statement extraction fallback failed: %s", llm_exc
        )

    preview = pages[0][:300] if pages else "<empty>"
    raise BankStatementParseError(
        f"No deterministic or LLM parser could extract this document. "
        f"First-page preview:\n{preview!r}"
    )


def detect_and_parse_all(
    pdf_bytes: bytes,
    *,
    source: str = "bank_statement_pdf",
    uri: str | None = None,
) -> list[EvidenceItem]:
    """Parse every currency/account section in *pdf_bytes*.

    Useful for multi-currency statements (e.g. a PayPal activity statement
    with CAD, AUD, USD columns).

    Returns an empty list if no parser recognises the document.
    """
    _ensure_parsers_loaded()
    pages = extract_pages(pdf_bytes)

    for parser in _PARSERS:
        if not parser.can_parse(pages):
            continue
        results = parser.parse_all(pages)
        return [
            r.to_evidence_item(source=source, uri=uri)
            for r in results
        ]

    # ── LLM fallback (single result) ─────────────────────────────────────────
    try:
        from .llm_extractor import llm_extract_statement

        result = llm_extract_statement(pages)
        return [result.to_evidence_item(source=source, uri=uri)]
    except Exception as llm_exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "LLM statement extraction fallback failed: %s", llm_exc
        )

    return []


def parse_with_parser(
    institution: str,
    pdf_bytes: bytes,
    *,
    account_ref: str | None = None,
    account_id: str | None = None,
    source: str = "bank_statement_pdf",
    uri: str | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> EvidenceItem:
    """Parse *pdf_bytes* using the parser registered for *institution*.

    Bypasses auto-detection – useful when the caller already knows the format.

    Raises:
        BankStatementParseError: if no parser is registered for *institution*,
            or if the chosen parser fails.
        ImportError: if no PDF library is installed.
    """
    _ensure_parsers_loaded()
    for parser in _PARSERS:
        if parser.institution != institution:
            continue
        pages = extract_pages(pdf_bytes)
        currency_filter = (extra_meta or {}).get("currency")
        if currency_filter:
            all_results = parser.parse_all(pages)
            match = next(
                (r for r in all_results if r.currency == currency_filter),
                None,
            )
            result = match or parser.parse(pages)
        else:
            result = parser.parse(pages)
        return result.to_evidence_item(
            account_ref=account_ref,
            account_id=account_id,
            source=source,
            uri=uri,
            extra_meta=extra_meta,
        )
    raise BankStatementParseError(
        f"No parser registered for institution '{institution}'. "
        f"Available: {[p.institution for p in _PARSERS]}"
    )
