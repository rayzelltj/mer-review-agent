"""Tests for the Evidence Ledger model."""

import uuid

from common.models.evidence_ledger import (
    EvidenceLedger,
    EvidenceLedgerEntry,
    StepType,
)


class TestEvidenceLedgerEntry:
    def test_default_fields(self):
        entry = EvidenceLedgerEntry()
        assert entry.entry_id  # UUID generated
        assert entry.timestamp  # ISO timestamp
        assert entry.step_type == StepType.EVIDENCE.value
        assert entry.content == ""
        assert entry.tool_name is None
        assert entry.confidence is None

    def test_to_dict_omits_none(self):
        entry = EvidenceLedgerEntry(
            run_id="run-1",
            agent="AccountingAgent",
            step_type="hypothesis",
            content="Cash variance may be due to unrecorded deposits",
        )
        d = entry.to_dict()
        assert d["run_id"] == "run-1"
        assert d["agent"] == "AccountingAgent"
        assert d["step_type"] == "hypothesis"
        assert "tool_name" not in d
        assert "confidence" not in d
        assert "parent_entry_id" not in d

    def test_to_dict_includes_set_optionals(self):
        entry = EvidenceLedgerEntry(
            run_id="run-1",
            agent="AccountingAgent",
            step_type="tool_call",
            content="Pulling GL detail",
            tool_name="qbo_get_gl_detail",
            tool_input_summary="account=1000",
            tool_output_summary="10 transactions found",
            confidence=0.85,
        )
        d = entry.to_dict()
        assert d["tool_name"] == "qbo_get_gl_detail"
        assert d["confidence"] == 0.85
        assert d["tool_output_summary"] == "10 transactions found"


class TestEvidenceLedger:
    def _make_ledger(self) -> EvidenceLedger:
        ledger = EvidenceLedger(run_id="run-123", client_id="acme", period_end="2026-01-31")
        return ledger

    def test_creation(self):
        ledger = self._make_ledger()
        assert ledger.run_id == "run-123"
        assert ledger.client_id == "acme"
        assert ledger.period_end == "2026-01-31"
        assert ledger.entries == []

    def test_add_entry_links_run_id(self):
        ledger = self._make_ledger()
        entry = EvidenceLedgerEntry(
            agent="AccountingAgent",
            step_type="hypothesis",
            content="Test hypothesis",
        )
        ledger.add_entry(entry)
        assert len(ledger.entries) == 1
        assert ledger.entries[0].run_id == "run-123"

    def test_get_hypothesis_chain(self):
        ledger = self._make_ledger()
        hyp_id = str(uuid.uuid4())

        # Add hypothesis
        hypothesis = EvidenceLedgerEntry(
            entry_id=hyp_id,
            agent="AccountingAgent",
            step_type="hypothesis",
            content="Cash variance from unrecorded deposits",
        )
        ledger.add_entry(hypothesis)

        # Add evidence linked to hypothesis
        evidence1 = EvidenceLedgerEntry(
            agent="AccountingAgent",
            step_type="evidence",
            content="GL shows 3 large deposits",
            parent_entry_id=hyp_id,
        )
        ledger.add_entry(evidence1)

        evidence2 = EvidenceLedgerEntry(
            agent="AccountingAgent",
            step_type="evidence",
            content="Bank statement confirms deposits",
            parent_entry_id=hyp_id,
        )
        ledger.add_entry(evidence2)

        # Add unrelated entry
        other = EvidenceLedgerEntry(
            agent="AccountingAgent",
            step_type="tool_call",
            content="Other tool call",
        )
        ledger.add_entry(other)

        chain = ledger.get_hypothesis_chain(hyp_id)
        assert len(chain) == 3  # hypothesis + 2 evidence
        assert chain[0].entry_id == hyp_id
        assert all(
            e.parent_entry_id == hyp_id or e.entry_id == hyp_id
            for e in chain
        )

    def test_get_hypothesis_chain_empty(self):
        ledger = self._make_ledger()
        chain = ledger.get_hypothesis_chain("nonexistent-id")
        assert chain == []

    def test_to_audit_trail(self):
        ledger = self._make_ledger()
        ledger.add_entry(EvidenceLedgerEntry(
            agent="AccountingAgent",
            step_type="hypothesis",
            content="Cash might be wrong",
            confidence=0.6,
        ))
        ledger.add_entry(EvidenceLedgerEntry(
            agent="AccountingAgent",
            step_type="tool_call",
            content="Checking GL",
            tool_name="qbo_get_gl_detail",
            tool_output_summary="Found 5 items",
        ))
        ledger.add_entry(EvidenceLedgerEntry(
            agent="AccountingAgent",
            step_type="conclusion",
            content="Cash is correct after review",
            confidence=0.95,
        ))

        trail = ledger.to_audit_trail()
        assert "# Evidence Ledger" in trail
        assert "run-123" in trail
        assert "Cash might be wrong" in trail
        assert "60%" in trail  # confidence formatted
        assert "Tool: qbo_get_gl_detail" in trail
        assert "Result: Found 5 items" in trail
        assert "95%" in trail

    def test_to_cosmos_doc(self):
        ledger = self._make_ledger()
        ledger.add_entry(EvidenceLedgerEntry(
            agent="AccountingAgent",
            step_type="conclusion",
            content="All clear",
        ))

        doc = ledger.to_cosmos_doc(session_id="evidence::run-123")
        assert doc["id"] == ledger.ledger_id
        assert doc["session_id"] == "evidence::run-123"
        assert doc["data_type"] == "evidence_ledger"
        assert doc["run_id"] == "run-123"
        assert doc["client_id"] == "acme"
        assert doc["period_end"] == "2026-01-31"
        assert doc["entry_count"] == 1
        assert len(doc["entries"]) == 1
        assert doc["entries"][0]["step_type"] == "conclusion"
        assert doc["entries"][0]["content"] == "All clear"

    def test_to_cosmos_doc_empty(self):
        ledger = self._make_ledger()
        doc = ledger.to_cosmos_doc(session_id="test")
        assert doc["entry_count"] == 0
        assert doc["entries"] == []


class TestStepType:
    def test_all_values(self):
        expected = {"hypothesis", "tool_call", "evidence", "conclusion", "escalation", "correction_applied"}
        actual = {st.value for st in StepType}
        assert actual == expected

    def test_string_enum(self):
        assert StepType.HYPOTHESIS == "hypothesis"
        assert StepType.CONCLUSION == "conclusion"
