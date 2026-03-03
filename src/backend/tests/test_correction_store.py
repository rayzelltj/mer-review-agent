"""Tests for the correction store."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Path to the module under test
_MODULE = "common.database.correction_store"


class _FakeContainer:
    """In-memory mock of a Cosmos container for testing."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def upsert_item(self, doc: dict) -> None:
        self.items[doc["id"]] = dict(doc)

    def read_item(self, *, item: str, partition_key: str) -> dict:
        if item not in self.items:
            raise Exception(f"Item {item} not found")
        doc = self.items[item]
        if doc.get("session_id") != partition_key:
            raise Exception(f"Partition key mismatch: {doc.get('session_id')} != {partition_key}")
        return dict(doc)

    def query_items(self, *, query: str, parameters: list, enable_cross_partition_query: bool = False):
        """Simple in-memory query filter based on parameters."""
        results = list(self.items.values())

        param_map = {p["name"]: p["value"] for p in parameters}

        filtered = []
        for item in results:
            if item.get("data_type") != "correction":
                continue
            if "@client_id" in param_map and item.get("client_id") != param_map["@client_id"]:
                continue
            if "@rule_id" in param_map:
                rule_id = item.get("rule_id")
                if rule_id is not None and rule_id != param_map["@rule_id"]:
                    continue

            # Check active filter
            if "c.active = true" in query and not item.get("active", True):
                continue

            filtered.append(item)

        # Sort by created_at DESC
        filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # Parse TOP N
        if "SELECT TOP" in query:
            import re
            match = re.search(r"SELECT TOP (\d+)", query)
            if match:
                limit = int(match.group(1))
                filtered = filtered[:limit]

        return filtered


@pytest.fixture
def fake_container():
    container = _FakeContainer()
    with patch(f"{_MODULE}.get_cosmos_container_client", return_value=container):
        yield container


class TestSaveCorrection:
    def test_basic_save(self, fake_container):
        from common.database.correction_store import save_correction

        doc = save_correction(
            client_id="acme",
            user_correction="These are retainers, not overdue",
            correction_type="classification",
            rule_id="BS-AP-AR-ITEMS-OLDER-60",
        )

        assert doc["client_id"] == "acme"
        assert doc["user_correction"] == "These are retainers, not overdue"
        assert doc["correction_type"] == "classification"
        assert doc["rule_id"] == "BS-AP-AR-ITEMS-OLDER-60"
        assert doc["active"] is True
        assert doc["times_applied"] == 0
        assert doc["data_type"] == "correction"
        assert doc["session_id"] == "corrections"
        assert doc["id"] in fake_container.items

    def test_save_with_all_fields(self, fake_container):
        from common.database.correction_store import save_correction

        doc = save_correction(
            client_id="acme",
            user_correction="Ignore seasonal balance",
            correction_type="ignore",
            rule_id="BS-CLEARING-ACCOUNTS-ZERO",
            account_ref="5100",
            original_output="Rule FAIL: clearing account has $10K balance",
            reasoning="Q4 marketing campaign uses this account",
            created_by="user@example.com",
            expires_months=6,
        )

        assert doc["account_ref"] == "5100"
        assert doc["original_output"].startswith("Rule FAIL")
        assert doc["reasoning"] == "Q4 marketing campaign uses this account"
        assert doc["created_by"] == "user@example.com"
        # Verify expiry is roughly 6 months out
        assert doc["expires_at"] > doc["created_at"]

    def test_save_without_rule_id(self, fake_container):
        from common.database.correction_store import save_correction

        doc = save_correction(
            client_id="acme",
            user_correction="General note",
            correction_type="general",
        )
        assert doc["rule_id"] is None


class TestGetCorrections:
    def _seed(self, fake_container, client_id: str, count: int = 3, active: bool = True):
        from common.database.correction_store import save_correction

        docs = []
        for i in range(count):
            doc = save_correction(
                client_id=client_id,
                user_correction=f"Correction {i}",
                correction_type="general",
                rule_id=f"RULE-{i}" if i % 2 == 0 else None,
            )
            if not active:
                doc["active"] = False
                fake_container.upsert_item(doc)
            docs.append(doc)
        return docs

    def test_get_by_client(self, fake_container):
        from common.database.correction_store import get_corrections

        self._seed(fake_container, "acme", 3)
        self._seed(fake_container, "other-client", 2)

        result = get_corrections("acme")
        assert len(result) == 3
        assert all(c["client_id"] == "acme" for c in result)

    def test_client_isolation(self, fake_container):
        from common.database.correction_store import get_corrections

        self._seed(fake_container, "acme", 2)
        self._seed(fake_container, "beta", 3)

        acme = get_corrections("acme")
        beta = get_corrections("beta")
        assert len(acme) == 2
        assert len(beta) == 3
        assert all(c["client_id"] == "acme" for c in acme)
        assert all(c["client_id"] == "beta" for c in beta)

    def test_filter_by_rule_id(self, fake_container):
        from common.database.correction_store import get_corrections

        self._seed(fake_container, "acme", 4)

        result = get_corrections("acme", rule_id="RULE-0")
        # Should include items with rule_id="RULE-0" or rule_id=None
        for c in result:
            assert c.get("rule_id") in ("RULE-0", None)

    def test_active_only(self, fake_container):
        from common.database.correction_store import get_corrections

        self._seed(fake_container, "acme", 2, active=True)
        self._seed(fake_container, "acme", 2, active=False)

        active = get_corrections("acme", active_only=True)
        all_corrections = get_corrections("acme", active_only=False)
        assert len(active) == 2
        assert len(all_corrections) == 4

    def test_max_results(self, fake_container):
        from common.database.correction_store import get_corrections

        self._seed(fake_container, "acme", 10)

        result = get_corrections("acme", max_results=3)
        assert len(result) == 3

    def test_empty_result(self, fake_container):
        from common.database.correction_store import get_corrections

        result = get_corrections("nonexistent-client")
        assert result == []


class TestDeactivateCorrection:
    def test_deactivate(self, fake_container):
        from common.database.correction_store import deactivate_correction, save_correction

        doc = save_correction(
            client_id="acme",
            user_correction="Test",
            correction_type="general",
        )
        assert doc["active"] is True

        success = deactivate_correction(doc["id"])
        assert success is True

        updated = fake_container.items[doc["id"]]
        assert updated["active"] is False

    def test_deactivate_nonexistent(self, fake_container):
        from common.database.correction_store import deactivate_correction

        success = deactivate_correction("nonexistent-id")
        assert success is False


class TestIncrementApplied:
    def test_increment(self, fake_container):
        from common.database.correction_store import increment_applied, save_correction

        doc = save_correction(
            client_id="acme",
            user_correction="Test",
            correction_type="general",
        )
        assert doc["times_applied"] == 0

        increment_applied(doc["id"])
        updated = fake_container.items[doc["id"]]
        assert updated["times_applied"] == 1
        assert updated["last_applied_at"] is not None

        increment_applied(doc["id"])
        updated = fake_container.items[doc["id"]]
        assert updated["times_applied"] == 2

    def test_increment_nonexistent_no_error(self, fake_container):
        from common.database.correction_store import increment_applied

        # Should not raise
        increment_applied("nonexistent-id")
