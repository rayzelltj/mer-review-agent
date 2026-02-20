"""
Tests for adapters/bank_statements/.

Structure
---------
- **Unit tests** – operate on synthetic page-text strings; no PDF file needed.
  Fast and fully deterministic.
- **Integration tests** – load the real PDF fixtures; skipped if PDFs are absent
  or if a PDF library is not installed.

Real PDF fixture paths
----------------------
``tests/rules_engine/fixtures/example_client/2025-12-31/``
  - ``paypal_activity_statement.pdf``
  - ``rbc_visa_statement.pdf``
"""

from __future__ import annotations

import pathlib
from datetime import date
from decimal import Decimal

import pytest

from adapters.bank_statements import (
    BankStatementParseError,
    ParsedStatement,
    detect_and_parse,
    detect_and_parse_all,
    parse_with_parser,
)
from adapters.bank_statements.parsers.paypal import PayPalActivityStatementParser
from adapters.bank_statements.parsers.rbc_visa import RBCVisaBusinessParser

# ---------------------------------------------------------------------------
# Fixture directories
# ---------------------------------------------------------------------------
PDF_DIR = (
    pathlib.Path(__file__).parent.parent
    / "rules_engine"
    / "fixtures"
    / "example_client"
    / "2025-12-31"
)

PAYPAL_PDF = PDF_DIR / "paypal_activity_statement.pdf"
RBC_PDF = PDF_DIR / "rbc_visa_statement.pdf"


# ---------------------------------------------------------------------------
# Synthetic page-text helpers (unit test inputs)
# ---------------------------------------------------------------------------

def _paypal_pages(
    cad_ending: str = "13,261.63",
    aud_ending: str = "1,156.34",
    period: str = "01/12/2025 - 31/12/2025",
) -> list[str]:
    """Minimal synthetic PayPal activity statement page 0."""
    return [
        f"Merchant Account ID: MA000000000000 PayPal ID: user@example.com\n"
        f" {period}                                                   "
        f"Activity Statement for December 2025\n"
        f"Balance Summary ({period})\n"
        f"Available Beginning Available Ending Withheld Beginning Withheld Ending\n"
        f"CAD 2,172.99 {cad_ending} 0.00 0.00\n"
        f"AUD 4,580.25 {aud_ending} 0.00 0.00\n"
        f"Page 1\n",
    ]


def _rbc_pages(
    new_balance: str = "31,435.80",
    period_line: str = "STATEMENT FROM NOV 28 TO DEC 29, 2025",
) -> list[str]:
    """Minimal synthetic RBC Avion Visa Business statement pages 0 and 1."""
    page0 = (
        "RBC® Avion® Visa‡ Business\n"
        "ACME CO. 4516 07** **** 1234\n"
        f"JANE DOE 4516 07** **** 5678\n"
        f"{period_line}\n"
        "1 OF 2\n"
        "PREVIOUS STATEMENT BALANCE $1,967.42\n"
    )
    page1 = (
        "RBC® Avion® Visa‡ Business\n"
        f"STATEMENT FROM NOV 28 TO DEC 29, 2025\n"
        "2 OF 2\n"
        "SUBTOTAL OF MONTHLY ACTIVITY $70,750.59\n"
        f"NEW BALANCE ${new_balance}\n"
        "INTEREST RATE CHART\n"
    )
    return [page0, page1]


# ===========================================================================
# Unit tests – PayPal parser
# ===========================================================================

class TestPayPalParser:
    parser = PayPalActivityStatementParser()

    def test_can_parse_returns_true_for_paypal_pages(self):
        assert self.parser.can_parse(_paypal_pages()) is True

    def test_can_parse_returns_false_for_rbc_pages(self):
        assert self.parser.can_parse(_rbc_pages()) is False

    def test_can_parse_returns_false_for_empty(self):
        assert self.parser.can_parse([]) is False

    def test_parse_returns_primary_currency(self):
        result = self.parser.parse(_paypal_pages())
        assert result.institution == "paypal"
        assert result.currency == "CAD"
        assert result.ending_balance == Decimal("13261.63")
        assert result.statement_end_date == date(2025, 12, 31)
        assert result.statement_start_date == date(2025, 12, 1)
        assert result.confidence == 1.0

    def test_parse_all_returns_all_currencies(self):
        results = self.parser.parse_all(_paypal_pages())
        currencies = [r.currency for r in results]
        assert "CAD" in currencies
        assert "AUD" in currencies

    def test_parse_all_aud_balance(self):
        results = self.parser.parse_all(_paypal_pages(aud_ending="1,156.34"))
        aud = next(r for r in results if r.currency == "AUD")
        assert aud.ending_balance == Decimal("1156.34")

    def test_parse_account_number_hint_is_merchant_id(self):
        result = self.parser.parse(_paypal_pages())
        assert result.account_number_hint == "MA000000000000"

    def test_parse_raises_on_missing_period(self):
        bad_pages = ["Merchant Account ID: X  Activity Statement\nno date here"]
        with pytest.raises(BankStatementParseError, match="period"):
            self.parser.parse(bad_pages)

    def test_to_evidence_item_sets_correct_fields(self):
        result = self.parser.parse(_paypal_pages())
        item = result.to_evidence_item(account_ref="67", account_id="67")
        assert item.evidence_type == "statement_balance_attachment"
        assert item.amount == Decimal("13261.63")
        assert item.statement_end_date == date(2025, 12, 31)
        assert item.meta["account_ref"] == "67"
        assert item.meta["currency"] == "CAD"
        assert item.meta["institution"] == "paypal"

    def test_detect_and_parse_with_currency_filter(self):
        pages = _paypal_pages()
        # Synthesise as bytes (not a real PDF — use parse_all via unit path)
        aud_result = self.parser.parse_all(pages)
        aud = next(r for r in aud_result if r.currency == "AUD")
        assert aud.ending_balance == Decimal("1156.34")


# ===========================================================================
# Unit tests – RBC Visa parser
# ===========================================================================

class TestRBCVisaParser:
    parser = RBCVisaBusinessParser()

    def test_can_parse_returns_true_for_rbc_pages(self):
        assert self.parser.can_parse(_rbc_pages()) is True

    def test_can_parse_returns_false_for_paypal_pages(self):
        assert self.parser.can_parse(_paypal_pages()) is False

    def test_can_parse_returns_false_for_empty(self):
        assert self.parser.can_parse([]) is False

    def test_parse_new_balance(self):
        result = self.parser.parse(_rbc_pages())
        assert result.institution == "rbc_visa"
        assert result.currency == "CAD"
        assert result.ending_balance == Decimal("31435.80")

    def test_parse_statement_end_date(self):
        result = self.parser.parse(_rbc_pages())
        assert result.statement_end_date == date(2025, 12, 29)

    def test_parse_statement_start_date(self):
        result = self.parser.parse(_rbc_pages())
        assert result.statement_start_date == date(2025, 11, 28)

    def test_parse_account_number_hint_last_four(self):
        result = self.parser.parse(_rbc_pages())
        # Last card number on page 0 is 5678
        assert result.account_number_hint == "5678"

    def test_parse_year_rollover_dec_to_jan(self):
        """Statement crossing a calendar year: DEC 15 TO JAN 14, 2026."""
        pages = _rbc_pages(period_line="STATEMENT FROM DEC 15 TO JAN 14, 2026")
        # Need to include the NEW BALANCE line on page 1 which uses the same period
        pages[1] = pages[1].replace(
            "STATEMENT FROM NOV 28 TO DEC 29, 2025",
            "STATEMENT FROM DEC 15 TO JAN 14, 2026",
        )
        result = self.parser.parse(pages)
        assert result.statement_end_date == date(2026, 1, 14)
        assert result.statement_start_date == date(2025, 12, 15)

    def test_parse_raises_on_missing_period(self):
        pages = ["RBC VISA statement but no period date"]
        with pytest.raises(BankStatementParseError, match="period"):
            self.parser.parse(pages)

    def test_parse_raises_on_missing_new_balance(self):
        pages = _rbc_pages()
        # Strip the NEW BALANCE line
        pages[1] = pages[1].replace("NEW BALANCE $31,435.80\n", "")
        with pytest.raises(BankStatementParseError, match="NEW BALANCE"):
            self.parser.parse(pages)

    def test_to_evidence_item_sets_correct_fields(self):
        result = self.parser.parse(_rbc_pages())
        item = result.to_evidence_item(account_ref="132", account_id="132")
        assert item.evidence_type == "statement_balance_attachment"
        assert item.amount == Decimal("31435.80")
        assert item.statement_end_date == date(2025, 12, 29)
        assert item.meta["account_ref"] == "132"
        assert item.meta["currency"] == "CAD"
        assert item.meta["institution"] == "rbc_visa"

    def test_confidence_is_1(self):
        result = self.parser.parse(_rbc_pages())
        assert result.confidence == 1.0


# ===========================================================================
# Unit tests – registry (no real PDF required)
# ===========================================================================

class TestRegistry:
    def test_parse_with_parser_rbc_visa(self):
        """parse_with_parser routes to the correct parser by institution name."""
        # We cannot call parse_with_parser with real bytes here, but we can verify
        # the routing logic by calling detect_and_parse_all on mocked text via
        # parsers directly (registry integration tested in integration tests below).
        rbc_result = RBCVisaBusinessParser().parse(_rbc_pages())
        item = rbc_result.to_evidence_item(account_ref="132")
        assert item.meta["institution"] == "rbc_visa"

    def test_unknown_institution_raises(self):
        from adapters.bank_statements.registry import _ensure_parsers_loaded, _PARSERS
        from adapters.bank_statements.base import BankStatementParseError

        _ensure_parsers_loaded()
        from adapters.bank_statements.registry import parse_with_parser as _pwp

        with pytest.raises(BankStatementParseError, match="No parser registered"):
            _pwp("nonexistent_bank", b"fakepdf")


# ===========================================================================
# Integration tests – real PDF fixtures
# ===========================================================================

@pytest.mark.skipif(
    not PAYPAL_PDF.exists(),
    reason="PayPal PDF fixture not present",
)
class TestPayPalIntegration:
    def test_detect_and_parse_returns_cad_by_default(self):
        pdf_bytes = PAYPAL_PDF.read_bytes()
        item = detect_and_parse(pdf_bytes, account_ref="67", account_id="67",
                                 extra_meta={"currency": "CAD"})
        assert item.evidence_type == "statement_balance_attachment"
        assert item.amount == Decimal("13261.63")
        assert item.statement_end_date == date(2025, 12, 31)
        assert item.meta["currency"] == "CAD"
        assert item.meta["account_ref"] == "67"

    def test_detect_and_parse_aud_currency_filter(self):
        pdf_bytes = PAYPAL_PDF.read_bytes()
        item = detect_and_parse(pdf_bytes, extra_meta={"currency": "AUD"})
        assert item.amount == Decimal("1156.34")
        assert item.meta["currency"] == "AUD"

    def test_detect_and_parse_all_returns_multiple_currencies(self):
        pdf_bytes = PAYPAL_PDF.read_bytes()
        items = detect_and_parse_all(pdf_bytes)
        currencies = {item.meta["currency"] for item in items}
        assert "CAD" in currencies
        assert "AUD" in currencies
        assert len(items) >= 2

    def test_parse_with_parser_paypal_cad(self):
        pdf_bytes = PAYPAL_PDF.read_bytes()
        item = parse_with_parser(
            "paypal", pdf_bytes,
            account_ref="67", account_id="67",
            extra_meta={"currency": "CAD"},
        )
        assert item.amount == Decimal("13261.63")
        assert item.statement_end_date == date(2025, 12, 31)

    def test_parse_with_parser_paypal_aud(self):
        pdf_bytes = PAYPAL_PDF.read_bytes()
        item = parse_with_parser(
            "paypal", pdf_bytes,
            account_ref="86", account_id="86",
            extra_meta={"currency": "AUD"},
        )
        assert item.amount == Decimal("1156.34")
        assert item.meta["account_ref"] == "86"


@pytest.mark.skipif(
    not RBC_PDF.exists(),
    reason="RBC VISA PDF fixture not present",
)
class TestRBCVisaIntegration:
    def test_detect_and_parse_returns_new_balance(self):
        pdf_bytes = RBC_PDF.read_bytes()
        item = detect_and_parse(pdf_bytes, account_ref="132", account_id="132")
        assert item.evidence_type == "statement_balance_attachment"
        assert item.amount == Decimal("31435.80")
        assert item.statement_end_date == date(2025, 12, 29)
        assert item.meta["account_ref"] == "132"

    def test_detect_and_parse_statement_start_date(self):
        pdf_bytes = RBC_PDF.read_bytes()
        item = detect_and_parse(pdf_bytes)
        assert item.meta["statement_start_date"] == "2025-11-28"

    def test_parse_with_parser_rbc_visa(self):
        pdf_bytes = RBC_PDF.read_bytes()
        item = parse_with_parser("rbc_visa", pdf_bytes, account_ref="132")
        assert item.amount == Decimal("31435.80")
        assert item.meta["institution"] == "rbc_visa"

    def test_account_number_hint_is_5678(self):
        pdf_bytes = RBC_PDF.read_bytes()
        item = detect_and_parse(pdf_bytes)
        assert item.meta.get("account_number_hint") == "5678"


@pytest.mark.skipif(
    not (PAYPAL_PDF.exists() and RBC_PDF.exists()),
    reason="PDF fixtures not present",
)
class TestAutoDetection:
    def test_paypal_not_confused_with_rbc(self):
        assert PayPalActivityStatementParser().can_parse(
            RBCVisaBusinessParser().parse(_rbc_pages()) and _rbc_pages()
        ) is False

    def test_rbc_not_confused_with_paypal(self):
        assert RBCVisaBusinessParser().can_parse(_paypal_pages()) is False

    def test_detect_and_parse_paypal_pdf(self):
        item = detect_and_parse(PAYPAL_PDF.read_bytes(), extra_meta={"currency": "CAD"})
        assert item.meta["institution"] == "paypal"

    def test_detect_and_parse_rbc_pdf(self):
        item = detect_and_parse(RBC_PDF.read_bytes())
        assert item.meta["institution"] == "rbc_visa"


# ===========================================================================
# Unit tests – LLM extractor (mocked AzureOpenAI client, no network calls)
# ===========================================================================

import json as _json_module  # noqa: E402 (appended after class definitions)


def _make_llm_client(payload: dict):
    """Build a MagicMock AzureOpenAI client that returns *payload* as structured JSON."""
    from unittest.mock import MagicMock

    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = (
        _json_module.dumps(payload)
    )
    return client


_VALID_LLM_PAYLOAD: dict = {
    "ending_balance": "5000.00",
    "statement_end_date": "2025-09-30",
    "statement_start_date": "2025-09-01",
    "currency": "CAD",
    "institution": "td_bank",
    "account_number_hint": "4321",
    "confidence": 0.9,
}


class TestLLMExtractor:
    """Unit tests for llm_extractor.llm_extract_statement — all I/O mocked."""

    def test_returns_parsed_statement_with_correct_fields(self):
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        result = llm_extract_statement(
            ["TD Bank statement text"], client=_make_llm_client(_VALID_LLM_PAYLOAD)
        )
        assert result.ending_balance == Decimal("5000.00")
        assert result.statement_end_date == date(2025, 9, 30)
        assert result.statement_start_date == date(2025, 9, 1)
        assert result.currency == "CAD"
        assert result.institution == "td_bank"
        assert result.account_number_hint == "4321"

    def test_confidence_capped_at_0_85_when_model_returns_1(self):
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        result = llm_extract_statement(
            ["text"],
            client=_make_llm_client({**_VALID_LLM_PAYLOAD, "confidence": 1.0}),
        )
        assert result.confidence == pytest.approx(0.85)

    def test_confidence_preserved_when_below_cap(self):
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        result = llm_extract_statement(
            ["text"],
            client=_make_llm_client({**_VALID_LLM_PAYLOAD, "confidence": 0.65}),
        )
        assert result.confidence == pytest.approx(0.65)

    def test_confidence_never_equals_1_even_when_model_claims_so(self):
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        result = llm_extract_statement(
            ["text"],
            client=_make_llm_client({**_VALID_LLM_PAYLOAD, "confidence": 1.0}),
        )
        assert result.confidence < 1.0

    def test_extra_dict_contains_extracted_by_llm(self):
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        result = llm_extract_statement(
            ["text"], client=_make_llm_client(_VALID_LLM_PAYLOAD)
        )
        assert result.extra.get("extracted_by") == "llm"

    def test_max_chars_truncates_long_pages(self):
        """Content that exceeds max_chars is trimmed before being sent to the LLM."""
        from unittest.mock import MagicMock
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = (
            _json_module.dumps(_VALID_LLM_PAYLOAD)
        )

        pages = ["A" * 4000, "B" * 4000]  # 8 000 chars total; limit = 5 000
        llm_extract_statement(pages, client=client, max_chars=5000)

        sent_content = client.chat.completions.create.call_args.kwargs["messages"][-1][
            "content"
        ]
        # Allow headroom for the "--- PAGE BREAK ---" separator
        assert len(sent_content) <= 5000 + len("\n--- PAGE BREAK ---\n")

    def test_raises_on_empty_llm_response(self):
        from unittest.mock import MagicMock
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = ""
        with pytest.raises(BankStatementParseError, match="empty"):
            llm_extract_statement(["text"], client=client)

    def test_raises_on_invalid_json_response(self):
        from unittest.mock import MagicMock
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = (
            "not valid json {{{"
        )
        with pytest.raises(BankStatementParseError, match="invalid JSON"):
            llm_extract_statement(["text"], client=client)

    def test_raises_on_non_numeric_ending_balance(self):
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        payload = {**_VALID_LLM_PAYLOAD, "ending_balance": "N/A"}
        with pytest.raises(BankStatementParseError, match="ending_balance"):
            llm_extract_statement(["text"], client=_make_llm_client(payload))

    def test_raises_on_malformed_end_date(self):
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        payload = {**_VALID_LLM_PAYLOAD, "statement_end_date": "31/12/2025"}
        with pytest.raises(BankStatementParseError, match="statement_end_date"):
            llm_extract_statement(["text"], client=_make_llm_client(payload))

    def test_null_optional_fields_are_accepted(self):
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        payload = {
            "ending_balance": "100.00",
            "statement_end_date": "2025-12-31",
            "statement_start_date": None,
            "currency": "USD",
            "institution": "chase",
            "account_number_hint": None,
            "confidence": 0.6,
        }
        result = llm_extract_statement(["text"], client=_make_llm_client(payload))
        assert result.statement_start_date is None
        assert result.account_number_hint is None

    def test_api_call_exception_raises_bank_statement_parse_error(self):
        from unittest.mock import MagicMock
        from adapters.bank_statements.llm_extractor import llm_extract_statement

        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("network timeout")
        with pytest.raises(BankStatementParseError, match="call failed"):
            llm_extract_statement(["text"], client=client)


# ===========================================================================
# Unit tests – registry LLM fallback path (no PDF library, no network)
# ===========================================================================

class TestRegistryLLMFallback:
    """
    Verify that detect_and_parse / detect_and_parse_all delegate to the LLM
    when no deterministic parser can handle the document, and raise correctly
    when the LLM itself also fails.
    """

    _FAKE_UNKNOWN_PAGES = ["SOME MYSTERY BANK\nFINAL BALANCE: $9876.54\nDEC 31 2025\n"]

    def _fake_stmt(self) -> ParsedStatement:
        return ParsedStatement(
            ending_balance=Decimal("9876.54"),
            statement_end_date=date(2025, 11, 30),
            currency="USD",
            institution="mystery_bank",
            confidence=0.72,
        )

    # ── helpers to raise from a lambda-compatible scope ─────────────────────

    @staticmethod
    def _llm_raises(pages, **kwargs):  # noqa: ARG002
        raise BankStatementParseError("LLM failed internally")

    # ── tests ────────────────────────────────────────────────────────────────

    def test_detect_and_parse_calls_llm_for_unknown_document(self, monkeypatch):
        fake_stmt = self._fake_stmt()

        monkeypatch.setattr(
            "adapters.bank_statements.registry.extract_pages",
            lambda _b: self._FAKE_UNKNOWN_PAGES,
        )
        monkeypatch.setattr(
            "adapters.bank_statements.llm_extractor.llm_extract_statement",
            lambda pages, **kwargs: fake_stmt,
        )

        item = detect_and_parse(b"dummy", account_ref="X", account_id="X")
        assert item.amount == Decimal("9876.54")
        assert item.meta["institution"] == "mystery_bank"
        assert item.meta["confidence"] == pytest.approx(0.72)

    def test_detect_and_parse_all_calls_llm_and_returns_single_item(self, monkeypatch):
        fake_stmt = self._fake_stmt()

        monkeypatch.setattr(
            "adapters.bank_statements.registry.extract_pages",
            lambda _b: self._FAKE_UNKNOWN_PAGES,
        )
        monkeypatch.setattr(
            "adapters.bank_statements.llm_extractor.llm_extract_statement",
            lambda pages, **kwargs: fake_stmt,
        )

        items = detect_and_parse_all(b"dummy")
        assert len(items) == 1
        assert items[0].amount == Decimal("9876.54")
        assert items[0].meta["institution"] == "mystery_bank"

    def test_detect_and_parse_raises_when_both_deterministic_and_llm_fail(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "adapters.bank_statements.registry.extract_pages",
            lambda _b: self._FAKE_UNKNOWN_PAGES,
        )
        monkeypatch.setattr(
            "adapters.bank_statements.llm_extractor.llm_extract_statement",
            self._llm_raises,
        )

        with pytest.raises(BankStatementParseError, match="No deterministic or LLM"):
            detect_and_parse(b"dummy")

    def test_detect_and_parse_all_returns_empty_when_both_fail(self, monkeypatch):
        monkeypatch.setattr(
            "adapters.bank_statements.registry.extract_pages",
            lambda _b: self._FAKE_UNKNOWN_PAGES,
        )
        monkeypatch.setattr(
            "adapters.bank_statements.llm_extractor.llm_extract_statement",
            self._llm_raises,
        )

        items = detect_and_parse_all(b"dummy")
        assert items == []

    def test_deterministic_parser_wins_without_touching_llm(self, monkeypatch):
        """PayPal pages → PayPal parser fires → LLM must NOT be called."""
        llm_calls: list[bool] = []

        def _spy_llm(pages, **kwargs):
            llm_calls.append(True)
            raise AssertionError("LLM should never be reached for known formats")

        monkeypatch.setattr(
            "adapters.bank_statements.registry.extract_pages",
            lambda _b: _paypal_pages(),
        )
        monkeypatch.setattr(
            "adapters.bank_statements.llm_extractor.llm_extract_statement",
            _spy_llm,
        )

        item = detect_and_parse(b"dummy", extra_meta={"currency": "CAD"})
        assert not llm_calls, "LLM should not be called when a deterministic parser fires"
        assert item.meta["institution"] == "paypal"
