"""Token-aware context truncation for agent prompts."""

from __future__ import annotations

import json
from typing import Any

# Rough estimate: 1 token ~ 3.5 characters for English text
CHARS_PER_TOKEN = 3.5


def truncate_tool_output(output: str, max_tokens: int = 4000) -> str:
    """Truncate tool output to fit within token budget.

    Strategy:
    1. If output fits, return as-is.
    2. If output is a JSON array, keep first N items + summary.
    3. If output is a JSON dict, serialize compact and truncate.
    4. Fallback: character truncation with marker.
    """
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    if len(output) <= max_chars:
        return output

    # Try to parse as JSON array and truncate items
    try:
        data = json.loads(output)
        if isinstance(data, list) and len(data) > 0:
            # Keep items until we approach the budget
            kept: list[Any] = []
            current_len = 2  # []
            for item in data:
                item_str = json.dumps(item)
                if current_len + len(item_str) + 2 > max_chars - 100:
                    break
                kept.append(item)
                current_len += len(item_str) + 2
            remaining = len(data) - len(kept)
            result = json.dumps(kept, indent=None)
            if remaining > 0:
                result = result[:-1] + f', "{remaining} more items omitted"]'
            return result
        elif isinstance(data, dict):
            # For dicts, serialize compact and truncate
            output = json.dumps(data, indent=None)
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: character truncation
    return output[:max_chars] + f"\n\n[... truncated, {len(output) - max_chars} chars omitted]"


def budget_corrections(corrections: list[dict], max_tokens: int = 1000) -> str:
    """Format corrections within token budget.

    Returns a formatted string with up to 5 most recent corrections,
    truncated to fit within the token budget.
    """
    if not corrections:
        return ""
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    lines = ["## Prior Corrections for This Client"]
    current_len = len(lines[0])

    for c in corrections[:5]:  # Max 5 corrections
        line = (
            f"- [{c.get('created_at', 'unknown')[:10]}] "
            f"Rule {c.get('rule_id', 'general')}: "
            f'"{c.get("user_correction", "")}" '
            f"(Type: {c.get('correction_type', 'general')}, "
            f"Active: {'yes' if c.get('active', True) else 'no'})"
        )
        if current_len + len(line) > max_chars:
            break
        lines.append(line)
        current_len += len(line)

    return "\n".join(lines)
