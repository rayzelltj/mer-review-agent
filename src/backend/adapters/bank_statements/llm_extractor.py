"""
LLM-based fallback extractor for unrecognised bank/CC statement formats.

Uses Azure OpenAI structured output (``response_format={"type": "json_schema"}``)
so the model is constrained to return a machine-readable JSON object — no
free-form prose that would need re-parsing.

This is intentionally *not* a ``BankStatementParser`` subclass.  It is called
by the registry only after every deterministic parser has declined the document,
and it always produces ``confidence < 1.0`` so downstream callers can flag the
result for human review.

Environment variables (same as the rest of the project)
--------------------------------------------------------
AZURE_OPENAI_ENDPOINT        required
AZURE_OPENAI_DEPLOYMENT_NAME default "gpt-4.1"
AZURE_OPENAI_API_VERSION     default "2024-11-20"
AZURE_OPENAI_API_KEY         optional (falls back to DefaultAzureCredential)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from decimal import Decimal, InvalidOperation

from .base import BankStatementParseError, ParsedStatement

LOGGER = logging.getLogger(__name__)

# ── JSON schema the model must conform to ────────────────────────────────────
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "ending_balance": {
            "type": "string",
            "description": "The statement closing/ending balance as a plain decimal string, e.g. '31435.80'. Always positive.",
        },
        "statement_end_date": {
            "type": "string",
            "description": "Last day of the statement period in ISO 8601 format YYYY-MM-DD.",
        },
        "statement_start_date": {
            "type": ["string", "null"],
            "description": "First day of the statement period in ISO 8601 format YYYY-MM-DD, or null if not found.",
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 three-letter currency code, e.g. CAD, USD, AUD.",
        },
        "institution": {
            "type": "string",
            "description": "Best-guess institution name, e.g. 'td_bank', 'bmo', 'cibc'. Use snake_case.",
        },
        "account_number_hint": {
            "type": ["string", "null"],
            "description": "Last 4 digits or other masked account identifier visible on the statement, or null.",
        },
        "confidence": {
            "type": "number",
            "description": "Self-assessed confidence in [0.0, 1.0]. Use < 0.8 when the document is unclear.",
        },
    },
    "required": [
        "ending_balance",
        "statement_end_date",
        "currency",
        "institution",
        "confidence",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
You are a financial document parser. Extract key fields from a bank or credit
card statement. Return ONLY the JSON object matching the schema provided.
Rules:
- ending_balance: the final closing/new/available balance for the statement period,
  always as a positive decimal string (no currency symbols, no commas).
- statement_end_date: last day covered by the statement, YYYY-MM-DD.
- currency: the ISO 4217 code for the primary currency shown on the statement.
- Do NOT guess or hallucinate amounts. If you cannot find a field with high
  confidence, set confidence to a value below 0.7.
"""


def _build_client():
    """Build an AzureOpenAI client using the same env-var convention as the project."""
    from openai import AzureOpenAI
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    if not endpoint:
        raise RuntimeError(
            "AZURE_OPENAI_ENDPOINT is required for LLM statement extraction."
        )
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-11-20").strip()
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    if api_key:
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    return AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=api_version,
    )


def llm_extract_statement(
    pages: list[str],
    *,
    max_chars: int = 6000,
    client=None,
    deployment: str | None = None,
) -> ParsedStatement:
    """Use an LLM to extract statement fields from unrecognised PDF text.

    Parameters
    ----------
    pages:
        Page text as returned by ``pdf_utils.extract_pages()``.
    max_chars:
        Maximum characters of page text sent to the LLM (cost/token guard).
        The first page is always fully included; subsequent pages are truncated
        if the running total would exceed this limit.
    client:
        Pre-built ``AzureOpenAI`` client (for testing/injection). If ``None``,
        one is created from environment variables.
    deployment:
        Azure OpenAI deployment name override. Defaults to
        ``AZURE_OPENAI_DEPLOYMENT_NAME`` env var or ``"gpt-4.1"``.

    Returns
    -------
    ParsedStatement
        ``institution`` is set to the model's best guess.
        ``confidence`` is whatever the model self-reported (always < 1.0 from
        this extractor since it is only reached for unknown formats).

    Raises
    ------
    BankStatementParseError
        If the LLM call fails or the response cannot be validated.
    """
    # ── Truncate text to stay within token budget ─────────────────────────────
    text_parts: list[str] = []
    total = 0
    for page in pages:
        if total >= max_chars:
            break
        chunk = page[: max_chars - total]
        text_parts.append(chunk)
        total += len(chunk)
    document_text = "\n--- PAGE BREAK ---\n".join(text_parts)

    # ── Build client / deployment ─────────────────────────────────────────────
    if client is None:
        client = _build_client()
    deploy = (deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")).strip()

    # ── Call with structured outputs ──────────────────────────────────────────
    try:
        response = client.chat.completions.create(
            model=deploy,
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "bank_statement_extraction",
                    "strict": True,
                    "schema": _RESPONSE_SCHEMA,
                },
            },
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": document_text},
            ],
            max_tokens=512,
        )
    except Exception as exc:
        raise BankStatementParseError(
            f"LLM statement extraction call failed: {exc}"
        ) from exc

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        raise BankStatementParseError("LLM returned an empty response.")

    # ── Parse and validate the JSON ───────────────────────────────────────────
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BankStatementParseError(
            f"LLM returned invalid JSON: {exc}\nRaw: {raw[:200]}"
        ) from exc

    try:
        ending_balance = Decimal(str(data["ending_balance"]).replace(",", ""))
    except (InvalidOperation, KeyError) as exc:
        raise BankStatementParseError(
            f"LLM extraction: invalid ending_balance '{data.get('ending_balance')}': {exc}"
        ) from exc

    try:
        statement_end_date = date.fromisoformat(data["statement_end_date"])
    except (ValueError, KeyError) as exc:
        raise BankStatementParseError(
            f"LLM extraction: invalid statement_end_date '{data.get('statement_end_date')}': {exc}"
        ) from exc

    start_raw = data.get("statement_start_date")
    statement_start_date: date | None = None
    if start_raw:
        try:
            statement_start_date = date.fromisoformat(start_raw)
        except ValueError:
            LOGGER.warning("LLM extraction: ignoring invalid statement_start_date '%s'", start_raw)

    confidence = float(data.get("confidence", 0.6))
    # Enforce: LLM fallback is never reported as 1.0 (that's reserved for deterministic parsers).
    confidence = min(confidence, 0.85)

    LOGGER.info(
        "LLM statement extraction: institution=%s currency=%s ending=%s end_date=%s confidence=%.2f",
        data.get("institution"),
        data.get("currency"),
        ending_balance,
        statement_end_date,
        confidence,
    )

    return ParsedStatement(
        ending_balance=ending_balance,
        statement_end_date=statement_end_date,
        statement_start_date=statement_start_date,
        currency=str(data.get("currency", "")).upper() or "UNKNOWN",
        institution=str(data.get("institution", "unknown_llm")),
        account_number_hint=data.get("account_number_hint") or None,
        confidence=confidence,
        extra={"extracted_by": "llm", "llm_deployment": deploy},
    )
