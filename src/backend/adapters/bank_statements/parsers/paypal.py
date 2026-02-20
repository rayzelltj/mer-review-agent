"""
Parser for PayPal Merchant Activity Statements (PDF).

Supported format
----------------
The PayPal merchant activity statement PDF has this structure:

  Page 0 – Balance Summary table (one row per currency):
    ``CAD  2,172.99  13,261.63  0.00  0.00``
    columns: currency | available_beginning | **available_ending** |
             withheld_beginning | withheld_ending

  Page 0 – Period header:
    ``01/12/2025 - 31/12/2025``  (DD/MM/YYYY)

  Page 0 – Merchant/account identity:
    ``Merchant Account ID: MA8VFGK6X3D6Q``
    ``PayPal ID: user@example.com``

Detection fingerprint
---------------------
Page 0 must contain both:
  - ``"Merchant Account ID:"``
  - ``"Activity Statement"``
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ..base import BankStatementParseError, BankStatementParser, ParsedStatement
from ..registry import _register

# ── Compiled patterns ─────────────────────────────────────────────────────────

# Period:  "01/12/2025 - 31/12/2025"  (DD/MM/YYYY)
_PERIOD_RE = re.compile(
    r"(\d{2})/(\d{2})/(\d{4})\s*[-–]\s*(\d{2})/(\d{2})/(\d{4})"
)

# Balance Summary row:
#   "CAD  2,172.99  13,261.63  0.00  0.00"
# Captures: currency, available_beginning (unused), available_ending.
_BALANCE_SUMMARY_ROW_RE = re.compile(
    r"^([A-Z]{3})\s+"               # currency code at line start
    r"([\d,]+\.\d{2})\s+"           # available_beginning
    r"([\d,]+\.\d{2})\s+"           # available_ending  ← we want this
    r"[\d,]+\.\d{2}\s+"             # withheld_beginning
    r"[\d,]+\.\d{2}",               # withheld_ending
    re.MULTILINE,
)

# Fallback: "Ending Available Balance  13,261.63  1,156.34  ..."
# (page 1 summary table, CAD is always the first column)
_ENDING_AVAILABLE_RE = re.compile(
    r"Ending Available Balance\s+([\d,]+\.\d{2})"
)

# Account number hint: last segment of Merchant Account ID
_MERCHANT_ID_RE = re.compile(r"Merchant Account ID:\s*(\S+)")


def _parse_decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _parse_ddmmyyyy(dd: str, mm: str, yyyy: str) -> date:
    return date(int(yyyy), int(mm), int(dd))


class PayPalActivityStatementParser(BankStatementParser):
    """Parses PayPal Merchant Activity Statements (multi-currency PDF)."""

    institution = "paypal"

    def can_parse(self, pages: list[str]) -> bool:
        if not pages:
            return False
        p0 = pages[0]
        return "Merchant Account ID:" in p0 and "Activity Statement" in p0

    def parse(self, pages: list[str]) -> ParsedStatement:
        """Return the first currency's ParsedStatement (usually the primary one)."""
        all_results = self.parse_all(pages)
        if not all_results:
            raise BankStatementParseError(
                "PayPal: no currency rows found in Balance Summary."
            )
        return all_results[0]

    def parse_all(self, pages: list[str]) -> list[ParsedStatement]:
        """Return one ParsedStatement per currency in the Balance Summary."""
        p0 = pages[0] if pages else ""
        full_text = "\n".join(pages)

        # ── Period ────────────────────────────────────────────────────────────
        period_match = _PERIOD_RE.search(p0)
        if not period_match:
            raise BankStatementParseError(
                "PayPal: could not find statement period (expected DD/MM/YYYY - DD/MM/YYYY)."
            )
        dd_s, mm_s, yyyy_s, dd_e, mm_e, yyyy_e = period_match.groups()
        start_date = _parse_ddmmyyyy(dd_s, mm_s, yyyy_s)
        end_date = _parse_ddmmyyyy(dd_e, mm_e, yyyy_e)

        # ── Merchant Account ID (used as account number hint) ─────────────────
        merchant_match = _MERCHANT_ID_RE.search(p0)
        merchant_id = merchant_match.group(1) if merchant_match else None

        # ── Balance Summary rows ──────────────────────────────────────────────
        rows = _BALANCE_SUMMARY_ROW_RE.findall(p0)
        # rows = list of (currency, available_beginning, available_ending)
        if not rows:
            # Fallback: try the "Ending Available Balance" line on page 1+
            # which lists values in column order (CAD first, then others).
            # We can only reliably extract one value this way.
            fallback_match = _ENDING_AVAILABLE_RE.search(full_text)
            if not fallback_match:
                raise BankStatementParseError(
                    "PayPal: could not parse Balance Summary or Ending Available Balance."
                )
            ending = _parse_decimal(fallback_match.group(1))
            return [
                ParsedStatement(
                    ending_balance=ending,
                    statement_end_date=end_date,
                    statement_start_date=start_date,
                    currency="CAD",  # best guess when table is unreadable
                    institution=self.institution,
                    account_number_hint=merchant_id,
                    confidence=0.6,
                )
            ]

        results: list[ParsedStatement] = []
        for currency, _beginning, ending_str in rows:
            results.append(
                ParsedStatement(
                    ending_balance=_parse_decimal(ending_str),
                    statement_end_date=end_date,
                    statement_start_date=start_date,
                    currency=currency,
                    institution=self.institution,
                    account_number_hint=merchant_id,
                    extra={"merchant_account_id": merchant_id} if merchant_id else {},
                    confidence=1.0,
                )
            )
        return results


# Register a singleton instance.
_register(PayPalActivityStatementParser())
