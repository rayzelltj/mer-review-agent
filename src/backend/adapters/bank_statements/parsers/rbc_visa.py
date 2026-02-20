"""
Parser for RBC Avion Visa Business statements (PDF).

Supported format
----------------
Page 0 header::

    RBC® Avion® Visa‡ Business
    ACME CO.                4516 07** **** 1234
    JANE DOE                4516 07** **** 5678
    STATEMENT FROM NOV 28 TO DEC 29, 2025

Page 1 (or any page) contains the closing balance line::

    NEW BALANCE $31,435.80

Detection fingerprint
---------------------
Page 0 must contain both ``"RBC"`` and ``"VISA"`` (case-insensitive).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ..base import BankStatementParseError, BankStatementParser, ParsedStatement
from ..registry import _register

# ── Month abbreviation map ────────────────────────────────────────────────────
_MONTHS: dict[str, int] = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# ── Compiled patterns ─────────────────────────────────────────────────────────

# "STATEMENT FROM NOV 28 TO DEC 29, 2025"
# Groups: start_mon, start_day, end_mon, end_day, year
_PERIOD_RE = re.compile(
    r"STATEMENT FROM\s+"
    r"([A-Z]{3})\s+(\d{1,2})\s+"
    r"TO\s+"
    r"([A-Z]{3})\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)

# "NEW BALANCE $31,435.80"
_NEW_BALANCE_RE = re.compile(
    r"NEW BALANCE\s+\$([\d,]+\.\d{2})"
)

# Account card number hint: "4516 07** **** 1760"  → captures last-4 "1760"
_CARD_NUMBER_RE = re.compile(
    r"\d{4}\s+\d{2}\*{2}\s+\*{4}\s+(\d{4})"
)


def _parse_decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


class RBCVisaBusinessParser(BankStatementParser):
    """Parses RBC Avion Visa Business monthly statements."""

    institution = "rbc_visa"

    def can_parse(self, pages: list[str]) -> bool:
        if not pages:
            return False
        p0_upper = pages[0].upper()
        return "RBC" in p0_upper and "VISA" in p0_upper

    def parse(self, pages: list[str]) -> ParsedStatement:
        full_text = "\n".join(pages)
        p0 = pages[0] if pages else ""

        # ── Period ────────────────────────────────────────────────────────────
        period_match = _PERIOD_RE.search(full_text)
        if not period_match:
            raise BankStatementParseError(
                "RBC Visa: could not find statement period "
                "(expected 'STATEMENT FROM MMM DD TO MMM DD, YYYY')."
            )
        start_mon, start_day, end_mon, end_day, year = period_match.groups()
        start_mon_upper = start_mon.upper()
        end_mon_upper = end_mon.upper()

        if start_mon_upper not in _MONTHS:
            raise BankStatementParseError(
                f"RBC Visa: unrecognised start month abbreviation '{start_mon}'."
            )
        if end_mon_upper not in _MONTHS:
            raise BankStatementParseError(
                f"RBC Visa: unrecognised end month abbreviation '{end_mon}'."
            )

        year_int = int(year)
        end_date = date(year_int, _MONTHS[end_mon_upper], int(end_day))
        # Start month may cross a year boundary (e.g. DEC → JAN next year handled below).
        start_month_int = _MONTHS[start_mon_upper]
        start_year = year_int if start_month_int <= _MONTHS[end_mon_upper] else year_int - 1
        start_date = date(start_year, start_month_int, int(start_day))

        # ── New Balance ───────────────────────────────────────────────────────
        balance_match = _NEW_BALANCE_RE.search(full_text)
        if not balance_match:
            raise BankStatementParseError(
                "RBC Visa: could not find 'NEW BALANCE $...' line."
            )
        ending_balance = _parse_decimal(balance_match.group(1))

        # ── Card number hint (last-4 of primary card) ─────────────────────────
        card_matches = _CARD_NUMBER_RE.findall(p0)
        # The statement shows multiple cards; take the last one listed (primary cardholder).
        account_number_hint = card_matches[-1] if card_matches else None

        return ParsedStatement(
            ending_balance=ending_balance,
            statement_end_date=end_date,
            statement_start_date=start_date,
            currency="CAD",
            institution=self.institution,
            account_number_hint=account_number_hint,
            confidence=1.0,
        )


# Register a singleton instance.
_register(RBCVisaBusinessParser())
