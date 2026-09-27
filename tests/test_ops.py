"""
システム・運用系エンドポイント (/health, /health/live, /health/ready, /livez, /readyz, /metrics) のテスト
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from portico.main import app

client = TestClient(app)


def test_health():
    """基本ヘルスチェック /health が 200 OK を返すこと"""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "portico"
    assert "mock" in data


def test_liveness():
    """Liveness プローブ (/livez) が 200 OK を返し、旧パス (/health/live) は 404 となること"""
    res = client.get("/livez")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_old = client.get("/health/live")
    assert res_old.status_code == 404


def test_readiness():
    """Readiness プローブ (/readyz) が 200 OK を返し、旧パス (/health/ready) は 404 となること"""
    res = client.get("/readyz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_old = client.get("/health/ready")
    assert res_old.status_code == 404


def test_metrics():
    """Prometheus 互換メトリクス /metrics が 200 OK かつテキスト形式で返ること"""
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers.get("content-type", "")
    assert "portico_up 1" in res.text


def test_openapi():
    """OpenAPI 仕様 JSON が 200 OK で返ること"""
    res = client.get("/openapi.json")
    assert res.status_code == 200
    data = res.json()
    assert "openapi" in data
    assert data["info"]["title"] == "Portico — MCP Gateway"


def test_resolve_url_helper():
    """_resolve_url ヘルパーの None/無効文字列判定"""
    from portico.main import _resolve_url

    assert _resolve_url(None) is None
    assert _resolve_url("") is None
    assert _resolve_url("  ") is None
    assert _resolve_url("none") is None
    assert _resolve_url("false") is None
    assert _resolve_url("null") is None
    assert _resolve_url("/custom/openapi.json") == "/custom/openapi.json"


def test_scalar_docs_endpoint(monkeypatch):
    """SCALAR_URL が設定されている場合、Scalar API Reference HTML が 200 OK で返ること"""
    import importlib
    import portico.core.config as config
    import portico.main as main_mod

    monkeypatch.setattr(config, "SCALAR_URL", "/scalar")
    monkeypatch.setattr(config, "OPENAPI_URL", "/openapi.json")
    monkeypatch.setattr(config, "ROOT_PATH", "/gateway")

    # リロードして Scalar ルートを登録
    reloaded_main = importlib.reload(main_mod)
    test_client = TestClient(reloaded_main.app)

    res = test_client.get("/scalar")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "@scalar/api-reference" in res.text
    assert "/gateway/openapi.json" in res.text

    # クリーンアップ: 元に戻して再度リロード
    monkeypatch.undo()
    importlib.reload(main_mod)


