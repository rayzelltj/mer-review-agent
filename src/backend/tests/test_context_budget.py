"""Tests for the context budget utilities."""

import json

from common.utils.context_budget import (
    CHARS_PER_TOKEN,
    budget_corrections,
    truncate_tool_output,
)


class TestTruncateToolOutput:
    def test_under_budget_passthrough(self):
        """Short output should pass through unchanged."""
        output = '{"accounts": [1, 2, 3]}'
        result = truncate_tool_output(output, max_tokens=4000)
        assert result == output

    def test_json_array_truncation_at_item_boundary(self):
        """Large JSON arrays should be truncated at item boundaries."""
        items = [{"id": i, "name": f"Account {i}", "balance": i * 1000.50} for i in range(200)]
        output = json.dumps(items)

        result = truncate_tool_output(output, max_tokens=500)
        assert len(result) < len(output)
        assert "more items omitted" in result

        # Should still be parseable JSON (up to the omitted marker)
        # The result has a trailing string element for the omitted count
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) < 200
        # Last element is the "N more items omitted" string
        assert isinstance(parsed[-1], str)
        assert "omitted" in parsed[-1]

    def test_json_array_empty(self):
        """Empty array should pass through."""
        output = "[]"
        result = truncate_tool_output(output, max_tokens=100)
        assert result == "[]"

    def test_json_dict_truncation(self):
        """Large JSON dicts should be compacted then character-truncated."""
        data = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}
        output = json.dumps(data, indent=2)

        result = truncate_tool_output(output, max_tokens=200)
        max_chars = int(200 * CHARS_PER_TOKEN)
        assert len(result) <= max_chars + 100  # Allow for truncation message
        assert "truncated" in result

    def test_plain_text_truncation(self):
        """Plain text should be character-truncated."""
        output = "A" * 50000
        result = truncate_tool_output(output, max_tokens=1000)
        max_chars = int(1000 * CHARS_PER_TOKEN)
        assert result.startswith("A" * 100)
        assert "truncated" in result
        assert "chars omitted" in result

    def test_exact_budget(self):
        """Output exactly at budget should pass through."""
        max_tokens = 100
        max_chars = int(max_tokens * CHARS_PER_TOKEN)
        output = "X" * max_chars
        result = truncate_tool_output(output, max_tokens=max_tokens)
        assert result == output

    def test_json_array_single_large_item(self):
        """Array with single oversized item should still produce valid output."""
        items = [{"data": "X" * 20000}]
        output = json.dumps(items)

        result = truncate_tool_output(output, max_tokens=500)
        # Should fall back to text truncation since item is too large
        assert len(result) < len(output)


class TestBudgetCorrections:
    def test_empty_corrections(self):
        """No corrections should return empty string."""
        assert budget_corrections([]) == ""

    def test_single_correction(self):
        result = budget_corrections([
            {
                "created_at": "2026-01-15T10:00:00Z",
                "rule_id": "BS-CASH-RECONCILED",
                "user_correction": "These are retainers, not overdue",
                "correction_type": "classification",
                "active": True,
            }
        ])
        assert "## Prior Corrections" in result
        assert "BS-CASH-RECONCILED" in result
        assert "retainers" in result
        assert "classification" in result
        assert "yes" in result  # active

    def test_max_five_corrections(self):
        """Should include at most 5 corrections even if more provided."""
        corrections = [
            {
                "created_at": f"2026-0{i+1}-01T00:00:00Z",
                "rule_id": f"RULE-{i}",
                "user_correction": f"Correction {i}",
                "correction_type": "general",
                "active": True,
            }
            for i in range(8)
        ]
        result = budget_corrections(corrections, max_tokens=5000)
        # Count correction lines (lines starting with "- [")
        correction_lines = [l for l in result.split("\n") if l.startswith("- [")]
        assert len(correction_lines) <= 5

    def test_three_corrections(self):
        corrections = [
            {
                "created_at": "2026-01-01T00:00:00Z",
                "rule_id": "RULE-A",
                "user_correction": "Fix A",
                "correction_type": "threshold",
                "active": True,
            },
            {
                "created_at": "2026-02-01T00:00:00Z",
                "rule_id": "RULE-B",
                "user_correction": "Fix B",
                "correction_type": "ignore",
                "active": False,
            },
            {
                "created_at": "2026-03-01T00:00:00Z",
                "rule_id": None,
                "user_correction": "General fix",
                "correction_type": "general",
                "active": True,
            },
        ]
        result = budget_corrections(corrections)
        assert "RULE-A" in result
        assert "RULE-B" in result
        assert "no" in result  # inactive correction
        assert "general" in result.lower()

    def test_budget_truncation(self):
        """Very tight budget should truncate corrections list."""
        corrections = [
            {
                "created_at": "2026-01-01T00:00:00Z",
                "rule_id": f"LONG-RULE-ID-{i}",
                "user_correction": "A" * 200,
                "correction_type": "general",
                "active": True,
            }
            for i in range(5)
        ]
        result = budget_corrections(corrections, max_tokens=50)
        # With very tight budget, should have fewer than 5 correction lines
        correction_lines = [l for l in result.split("\n") if l.startswith("- [")]
        assert len(correction_lines) < 5

    def test_six_corrections_capped_at_five(self):
        corrections = [
            {
                "created_at": f"2026-01-{i+1:02d}T00:00:00Z",
                "rule_id": f"R-{i}",
                "user_correction": f"Fix {i}",
                "correction_type": "general",
                "active": True,
            }
            for i in range(6)
        ]
        result = budget_corrections(corrections, max_tokens=5000)
        correction_lines = [l for l in result.split("\n") if l.startswith("- [")]
        assert len(correction_lines) <= 5
