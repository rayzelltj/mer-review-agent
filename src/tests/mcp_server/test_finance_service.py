"""
Tests for Finance MCP service registration.
"""

from pathlib import Path
import sys

MCP_SERVER_ROOT = Path(__file__).resolve().parents[2] / "mcp_server"
if str(MCP_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER_ROOT))

from core.factory import Domain


class TestFinanceService:
    def test_register_tools_includes_balance_sheet_pipeline(self, mock_mcp_server):
        from services.finance_service import FinanceService

        service = FinanceService()
        service.register_tools(mock_mcp_server)

        names = {tool["func"].__name__ for tool in mock_mcp_server.tools}

        required = {
            "qbo_connection_status",
            "get_or_create_balance_sheet_review",
            "bs_fetch_data",
            "bs_normalize_data",
            "bs_run_rules",
            "bs_get_findings",
            "bs_submit_evidence_request",
        }
        missing = required - names
        assert not missing, f"Missing finance tools: {sorted(missing)}"

    def test_registered_finance_tools_are_tagged(self, mock_mcp_server):
        from services.finance_service import FinanceService

        service = FinanceService()
        service.register_tools(mock_mcp_server)

        for tool in mock_mcp_server.tools:
            assert Domain.FINANCE.value in tool["tags"]

    def test_status_next_step_guidance_handles_terminal_reuse_states(self):
        from services.finance_service import _status_next_step_guidance

        assert "bs_normalize_data" in _status_next_step_guidance("raw")
        assert "bs_run_rules" in _status_next_step_guidance("fetched")
        assert "bs_get_findings" in _status_next_step_guidance("done")
        assert "bs_fetch_data" in _status_next_step_guidance("failed")

    def test_bs_fetch_data_reused_done_run_returns_done_guidance(
        self, mock_mcp_server, monkeypatch
    ):
        from services import finance_service
        from services.finance_service import FinanceService

        def fake_request_json(method, path, **kwargs):
            if method == "GET" and path.startswith("/api/reviews/balance-sheet/find"):
                return {"run_id": "run_123", "status": "done"}
            raise AssertionError(f"Unexpected request {method} {path}")

        monkeypatch.setattr(finance_service, "_request_json", fake_request_json)

        service = FinanceService()
        service.register_tools(mock_mcp_server)
        bs_fetch_data = next(
            tool["func"] for tool in mock_mcp_server.tools if tool["func"].__name__ == "bs_fetch_data"
        )

        response = bs_fetch_data("Blackbird Fabrics Inc.", "2026-01-31")

        assert "status=done" in response
        assert "bs_get_findings" in response
        assert "wait for status=raw" not in response.lower()
