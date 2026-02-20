"""
Bank statement PDF adapter.

Public API
----------
::

    from adapters.bank_statements import detect_and_parse, detect_and_parse_all, parse_with_parser
    from adapters.bank_statements import BankStatementParser, ParsedStatement, BankStatementParseError
    from adapters.bank_statements import llm_extract_statement  # optional LLM fallback

``detect_and_parse(pdf_bytes, ...)``
    Auto-detect institution and return one ``EvidenceItem``.

``detect_and_parse_all(pdf_bytes, ...)``
    Auto-detect and return all currency/account sections as ``list[EvidenceItem]``.

``parse_with_parser(institution, pdf_bytes, ...)``
    Force a specific institution parser (bypass detection).

Extending
---------
Add a new institution by:

1. Create ``adapters/bank_statements/parsers/<institution>.py``.
2. Implement a ``BankStatementParser`` subclass.
3. Call ``_register(MyParser())`` at module level.
4. Import the module in ``adapters/bank_statements/registry._ensure_parsers_loaded()``.
"""

from .base import BankStatementParseError, BankStatementParser, ParsedStatement
from .llm_extractor import llm_extract_statement
from .registry import detect_and_parse, detect_and_parse_all, parse_with_parser

__all__ = [
    "BankStatementParseError",
    "BankStatementParser",
    "ParsedStatement",
    "detect_and_parse",
    "detect_and_parse_all",
    "llm_extract_statement",
    "parse_with_parser",
]
