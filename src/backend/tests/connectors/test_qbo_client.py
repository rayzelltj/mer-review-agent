from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from connectors.qbo.auth import ensure_access_token_valid
from connectors.qbo.client import qbo_get
from connectors.qbo.config import QBOConfig


def _config(access_token: str = "token", expires_at: str = "2099-01-01T00:00:00+00:00") -> QBOConfig:
    return QBOConfig(
        env="sandbox",
        base_url="https://sandbox-quickbooks.api.intuit.com",
        client_id="cid",
        client_secret="secret",
        realm_id="123",
        access_token=access_token,
        refresh_token="refresh",
        token_expires_at=expires_at,
    )


def test_qbo_get_builds_url_and_headers():
    cfg = _config(access_token="newtoken")
    response = Mock()
    response.read.return_value = b'{"ok": true}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)

    captured = {}

    def _fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return response

    with patch("connectors.qbo.client.urlopen", _fake_urlopen):
        out = qbo_get(
            cfg,
            "/v3/company/123/reports/BalanceSheet",
            params={"end_date": "2025-11-30", "accounting_method": "Accrual"},
        )

    assert out["ok"] is True
    assert captured["auth"] == "Bearer newtoken"
    parsed = urlparse(captured["url"])
    assert parsed.path == "/v3/company/123/reports/BalanceSheet"
    qs = parse_qs(parsed.query)
    assert qs["end_date"] == ["2025-11-30"]
    assert qs["accounting_method"] == ["Accrual"]


def test_refresh_when_expired():
    expired = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
    cfg = _config(expires_at=expired)
    refreshed = _config(access_token="fresh", expires_at="2099-01-01T00:00:00+00:00")

    with patch("connectors.qbo.auth.refresh_access_token", return_value=refreshed) as refresh:
        out = ensure_access_token_valid(cfg)
        refresh.assert_called_once()
        assert out.access_token == "fresh"
