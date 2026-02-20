"""
Base types for bank/credit-card statement parsers.

Architecture
------------
- ``BankStatementParser``  – abstract base; one subclass per institution format.
- ``ParsedStatement``      – typed result of a successful parse.
- ``BankStatementParseError`` – raised when a recognised format fails to extract data.

Parsers are pure functions of *text* (``list[str]``, one entry per PDF page).
They never perform I/O or call PDF libraries; that responsibility belongs to
``pdf_utils.extract_pages()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from common.rules_engine.models import EvidenceItem


class BankStatementParseError(ValueError):
    """Raised when a recognised statement format fails to parse cleanly."""


@dataclass(frozen=True)
class ParsedStatement:
    """Normalised output of a single bank/CC statement parse."""

    ending_balance: Decimal
    """The closing/ending balance for the statement period (always positive)."""

    statement_end_date: date
    """Last day covered by the statement."""

    currency: str
    """ISO 4217 currency code, e.g. "CAD", "USD"."""

    institution: str
    """Machine-friendly institution key, e.g. "paypal", "rbc_visa"."""

    statement_start_date: date | None = None
    """First day covered by the statement (None if not parseable)."""

    account_number_hint: str | None = None
    """Last 4 digits or other masked identifier (None if not present)."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Any additional parser-specific metadata."""

    confidence: float = 1.0
    """Self-reported parse confidence in [0.0, 1.0]."""

    def to_evidence_item(
        self,
        *,
        account_ref: str | None = None,
        account_id: str | None = None,
        source: str = "bank_statement_pdf",
        uri: str | None = None,
        extra_meta: dict[str, Any] | None = None,
    ) -> EvidenceItem:
        """Convert to a canonical ``EvidenceItem`` for the rules engine."""
        meta: dict[str, Any] = {
            "institution": self.institution,
            "currency": self.currency,
            "parser": f"bank_statements.{self.institution}",
            "confidence": self.confidence,
        }
        if self.account_number_hint:
            meta["account_number_hint"] = self.account_number_hint
        if self.statement_start_date:
            meta["statement_start_date"] = self.statement_start_date.isoformat()
        if account_ref:
            meta["account_ref"] = account_ref
        if account_id:
            meta["account_id"] = account_id
        if self.extra:
            meta.update(self.extra)
        if extra_meta:
            meta.update(extra_meta)

        return EvidenceItem(
            evidence_type="statement_balance_attachment",
            source=source,
            statement_end_date=self.statement_end_date,
            amount=self.ending_balance,
            uri=uri,
            meta=meta,
        )


class BankStatementParser(ABC):
    """
    Abstract base for institution-specific bank/CC statement parsers.

    Subclasses must:
    1. Set ``institution`` (class variable).
    2. Implement ``can_parse(pages)`` – fast fingerprint check, no exceptions.
    3. Implement ``parse(pages)`` – full extraction, may raise ``BankStatementParseError``.

    Optionally, override ``parse_all(pages)`` when a single PDF contains
    per-currency or per-account sections (e.g. PayPal multi-currency statements).
    """

    #: Machine-friendly key, e.g. "paypal" or "rbc_visa".
    institution: str = ""

    @abstractmethod
    def can_parse(self, pages: list[str]) -> bool:
        """Return True if this parser recognises the statement format.

        Must be cheap (no regex loops over full text) and must never raise.
        """

    @abstractmethod
    def parse(self, pages: list[str]) -> ParsedStatement:
        """Parse and return the primary ``ParsedStatement``.

        For multi-currency statements the *primary* result is the first/largest
        currency section. Use ``parse_all()`` to retrieve every currency.

        Raises:
            BankStatementParseError: if required fields cannot be extracted.
        """

    def parse_all(self, pages: list[str]) -> list[ParsedStatement]:
        """Return one ``ParsedStatement`` per currency/account section.

        Default implementation delegates to ``parse()`` (single-section).
        Parsers that support multi-currency documents should override this.
        """
        return [self.parse(pages)]
