from unittest.mock import patch

from connectors.qbo.config import QBOConfig
from connectors.qbo.reports import fetch_profit_and_loss


def _config() -> QBOConfig:
    return QBOConfig(
        env="sandbox",
        base_url="https://sandbox-quickbooks.api.intuit.com",
        client_id="cid",
        client_secret="secret",
        realm_id="123",
        access_token="token",
        refresh_token="refresh",
        token_expires_at="2099-01-01T00:00:00+00:00",
    )


def test_fetch_profit_and_loss_passes_summarize_column_by():
    cfg = _config()
    with patch("connectors.qbo.reports.qbo_get") as qbo_get:
        qbo_get.return_value = {"ok": True}
        fetch_profit_and_loss(
            cfg,
            start_date="2025-08-01",
            end_date="2025-11-30",
            summarize_column_by="Month",
        )

        qbo_get.assert_called_once()
        args, kwargs = qbo_get.call_args
        assert args[0] == cfg
        assert args[1] == "/v3/company/123/reports/ProfitAndLoss"
        assert kwargs["params"]["summarize_column_by"] == "Month"
        assert kwargs["params"]["start_date"] == "2025-08-01"
        assert kwargs["params"]["end_date"] == "2025-11-30"
