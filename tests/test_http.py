"""HTTP entry point: health check, shop-key authentication, and key parsing. No real network needed."""
import pytest
from starlette.testclient import TestClient

from backend.app.mcp_server.http_app import create_app, load_shop_keys, shop_for_key

KEY_A = "a" * 32
KEY_B = "b" * 32
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VARAVU_DB", str(tmp_path / "http.db"))
    with TestClient(create_app({"shopA": KEY_A, "shopB": KEY_B}, hosts=["testserver"])) as c:
        yield c


def test_health_needs_no_key(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_mcp_rejects_missing_key(client):
    assert client.post("/mcp", json={}, headers=MCP_HEADERS).status_code == 401


def test_mcp_rejects_wrong_key(client):
    response = client.post("/mcp", json={}, headers={**MCP_HEADERS, "Authorization": "Bearer " + "x" * 32})
    assert response.status_code == 401


def test_valid_key_reaches_mcp(client):
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}}}
    response = client.post("/mcp", json=body, headers={**MCP_HEADERS, "Authorization": f"Bearer {KEY_A}"})
    assert response.status_code == 200 and "varavu" in response.text


def test_keys_parse_and_match():
    keys = load_shop_keys(f"shop-a:{KEY_A},shop-b:{KEY_B}")
    assert shop_for_key(KEY_B, keys) == "shop-b"
    assert shop_for_key("c" * 32, keys) is None


@pytest.mark.parametrize("raw", ["shopA", "shopA:short", ":" + KEY_A])
def test_bad_key_config_is_refused(raw):
    with pytest.raises(ValueError):
        load_shop_keys(raw)


def test_unknown_host_is_refused(client_factory=None):
    with TestClient(create_app({"shopA": KEY_A}, hosts=["only.example.com"])) as c:
        response = c.post("/mcp", json={}, headers={**MCP_HEADERS, "Authorization": f"Bearer {KEY_A}"})
        assert response.status_code == 421


def test_app_refuses_to_start_without_keys(monkeypatch):
    monkeypatch.delenv("VARAVU_SHOP_KEYS", raising=False)
    with pytest.raises(RuntimeError):
        create_app()
