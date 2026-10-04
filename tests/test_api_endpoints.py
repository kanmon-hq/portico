"""
Unit and integration tests for FastAPI routes and dependency injection.
"""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from portico.storage.factory import get_server_repository


class TestDependencyInjection:
    """api/deps.py のテナントIDおよびシークレット検証テスト。"""

    def test_get_tenant_id_from_header(self, client: TestClient):
        """X-Tenant-ID ヘッダーからテナントIDが抽出される。"""
        repo = get_server_repository()
        asyncio.run(
            repo.create_server(
                "tenant_header_123",
                {
                    "id": "srv-h1",
                    "name": "H1",
                    "url": "https://h1.example.com",
                    "status": "active",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            )
        )
        resp = client.get("/v1/servers", headers={"X-Tenant-ID": "tenant_header_123"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["tenant_id"] == "tenant_header_123"

    def test_get_tenant_id_from_query(self, client: TestClient):
        """クエリパラメータ tenant_id からテナントIDが抽出される。"""
        repo = get_server_repository()
        asyncio.run(
            repo.create_server(
                "tenant_query_456",
                {
                    "id": "srv-q1",
                    "name": "Q1",
                    "url": "https://q1.example.com",
                    "status": "active",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            )
        )
        resp = client.get("/v1/servers?tenant_id=tenant_query_456")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["tenant_id"] == "tenant_query_456"

    def test_get_tenant_id_default(self, client: TestClient):
        """指定がない場合は tenant_default となる。"""
        repo = get_server_repository()
        asyncio.run(
            repo.create_server(
                "tenant_default",
                {
                    "id": "srv-d1",
                    "name": "D1",
                    "url": "https://d1.example.com",
                    "status": "active",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            )
        )
        resp = client.get("/v1/servers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["tenant_id"] == "tenant_default"

    def test_internal_api_key_forbidden_when_missing_or_invalid(self, client: TestClient, monkeypatch):
        """内部APIに不正または欠落した Authorization Bearer トークンを渡すと 401 または 403 となる。"""
        monkeypatch.setattr("portico.api.deps.INTERNAL_API_KEY", "test-internal-key-12345")

        resp_missing = client.delete("/v1/internal/tenants/t1")
        assert resp_missing.status_code == 401

        resp_invalid = client.delete(
            "/v1/internal/tenants/t1",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp_invalid.status_code == 403

    def test_internal_api_key_disabled_when_not_configured(self, client: TestClient, monkeypatch):
        """INTERNAL_API_KEY が未設定の場合は 401 で拒絶される。"""
        monkeypatch.setattr("portico.api.deps.INTERNAL_API_KEY", None)
        resp = client.delete(
            "/v1/internal/tenants/t1",
            headers={"Authorization": "Bearer any-key"},
        )
        assert resp.status_code == 401

    def test_internal_api_key_authorized(self, client: TestClient, monkeypatch):
        """正しい INTERNAL_API_KEY Bearer トークンで内部APIにアクセスできる。"""
        test_key = "internal-secret-key-abcdef"
        monkeypatch.setattr("portico.api.deps.INTERNAL_API_KEY", test_key)

        resp = client.delete(
            "/v1/internal/tenants/tenant_clean",
            headers={"Authorization": f"Bearer {test_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["tenant_id"] == "tenant_clean"


class TestServerRoutes:
    """api/routes/servers.py のテスト。"""

    def test_list_servers(self, client: TestClient):
        """サーバー一覧の取得。"""
        resp = client.get("/v1/servers", headers={"X-Tenant-ID": "tenant_srv_test"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_register_server_ssrf_blocked(self, client: TestClient):
        """SSRF に該当する不正な URL は 422 バリデーションエラーとなる。"""
        resp = client.post(
            "/v1/servers",
            headers={"X-Tenant-ID": "tenant_srv_test"},
            json={"name": "Evil Server", "url": "http://169.254.169.254/latest"},
        )
        assert resp.status_code == 422

    def test_register_server_success(self, client: TestClient):
        """正常な外部サーバーの登録。"""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
            with patch("httpx.AsyncClient.post", return_value=AsyncMock(status_code=200)):
                resp = client.post(
                    "/v1/servers",
                    headers={"X-Tenant-ID": "tenant_srv_test"},
                    json={"name": "Confluence MCP", "url": "https://confluence.example.com"},
                )
                assert resp.status_code == 201
                data = resp.json()
                assert data["name"] == "Confluence MCP"
                assert data["status"] == "active"
                assert data["tenant_id"] == "tenant_srv_test"

    def test_delete_nonexistent_server_returns_404(self, client: TestClient):
        """存在しない外部サーバーの削除は 404 となる。"""
        resp = client.delete("/v1/servers/ext-nonexist", headers={"X-Tenant-ID": "tenant_srv_test"})
        assert resp.status_code == 404

    def test_delete_external_server_success(self, client: TestClient):
        """登録済み外部サーバーの削除成功。"""
        repo = get_server_repository()
        asyncio.run(
            repo.create_server(
                "tenant_del_route",
                {
                    "id": "ext-123",
                    "name": "To Delete",
                    "url": "https://delete.example.com",
                    "status": "active",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            )
        )

        resp = client.delete("/v1/servers/ext-123", headers={"X-Tenant-ID": "tenant_del_route"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["id"] == "ext-123"

    def test_create_server_with_bearer_auth(self, client: TestClient):
        """Bearer 認証付きの外部サーバー登録と平文トークン非露出を検証。"""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
            with patch("httpx.AsyncClient.post", return_value=AsyncMock(status_code=200)):
                resp = client.post(
                    "/v1/servers",
                    headers={"X-Tenant-ID": "tenant_api_auth"},
                    json={
                        "name": "Auth API Server",
                        "url": "https://api-auth.example.com",
                        "auth_type": "bearer",
                        "auth_token": "super-secret-token",
                    },
                )
                assert resp.status_code == 201
                data = resp.json()
                assert data["auth_type"] == "bearer"
                assert data["has_auth"] is True
                assert "super-secret-token" not in resp.text


class TestToolDispatchService:
    """ツールディスパッチおよびプロキシ実行ロジックのテスト。"""

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_404(self):
        """未登録のツール呼び出しは HTTPException(404) となる。"""
        from fastapi import HTTPException

        from portico.services.server_service import dispatch_tool_call

        with pytest.raises(HTTPException) as exc_info:
            await dispatch_tool_call(
                "completely_nonexistent_tool",
                {"foo": "bar"},
                tenant_id="tenant_tool_test",
            )
        assert exc_info.value.status_code == 404
        assert "Unknown tool" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_execute_external_tool_with_auth(self):
        """外部 MCP サーバーへのツール実行プロキシ時に認証ヘッダーが付与される。"""
        from portico.services.crypto import encrypt_auth_config
        from portico.services.server_service import dispatch_tool_call

        enc = encrypt_auth_config(
            {
                "auth_type": "bearer",
                "headers": {"Authorization": "Bearer ext-token-999"},
            }
        )
        repo = get_server_repository()
        await repo.create_server(
            "tenant_proxy_auth",
            {
                "id": "ext-proxy-1",
                "name": "Proxy Target",
                "url": "https://proxy.example.com",
                "auth_type": "bearer",
                "encrypted_auth_config": enc,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )

        mock_resp = httpx.Response(200, json={"jsonrpc": "2.0", "result": {"value": 42}})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            result = await dispatch_tool_call(
                "ext_calc",
                {"x": 20, "y": 22},
                tenant_id="tenant_proxy_auth",
            )
            assert result["value"] == 42

            # プロキシリクエストのヘッダーに Bearer トークンが付与されていること
            mock_post.assert_awaited()
            call_headers = mock_post.call_args[1].get("headers", {})
            assert call_headers.get("Authorization") == "Bearer ext-token-999"
            call_json = mock_post.call_args[1].get("json", {})
            assert call_json.get("method") == "tools/call"
            assert call_json.get("params", {}).get("name") == "ext_calc"

    @pytest.mark.asyncio
    async def test_execute_namespaced_tool_targeted_routing(self):
        """名前空間付きツール名 ({server_slug}__{tool}) で呼び出した際、対象サーバーにのみプロキシ転送されることを検証。"""
        from portico.services.server_service import dispatch_tool_call

        repo = get_server_repository()
        await repo.create_server(
            "tenant_route_test",
            {
                "id": "srv-alpha",
                "name": "Alpha Service",
                "url": "https://alpha.example.com",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )
        await repo.create_server(
            "tenant_route_test",
            {
                "id": "srv-beta",
                "name": "Beta Service",
                "url": "https://beta.example.com",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )

        mock_post_resp = httpx.Response(200, json={"jsonrpc": "2.0", "result": {"server": "alpha"}})

        with patch("httpx.AsyncClient.post", return_value=mock_post_resp) as mock_post:
            # Alpha 側の名前空間で実行
            result = await dispatch_tool_call(
                "alpha_service__deploy",
                {"env": "staging"},
                tenant_id="tenant_route_test",
            )
            assert result["server"] == "alpha"

            called_url = mock_post.call_args[0][0]
            parsed_called_url = urlparse(called_url)
            assert parsed_called_url.scheme == "https"
            assert parsed_called_url.hostname == "alpha.example.com"
            call_json = mock_post.call_args[1].get("json", {})
            assert call_json.get("method") == "tools/call"
            assert call_json.get("params", {}).get("name") == "deploy"


@pytest.mark.asyncio
async def test_app_lifespan():
    """FastAPI アプリケーションの lifespan startup / shutdown ライフサイクルが正常に完走すること"""
    from portico.main import app, lifespan

    async with lifespan(app):
        # Startup completed
        repo = get_server_repository()
        assert repo is not None


def test_get_scopes_helper():
    """get_scopes 依存性関数のパース動作検証"""
    from portico.api.deps import get_scopes

    assert get_scopes(None, None) is None
    assert get_scopes("read,write", None) == ["read", "write"]
    assert get_scopes(None, "admin audit") == ["admin", "audit"]
    assert get_scopes("read, read, write", None) == ["read", "write"]
