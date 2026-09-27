"""
Unit tests for external MCP server management and tool aggregation service.
"""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import urlparse

import httpx
import pytest
from fastapi import HTTPException

from portico.schemas.server import AuthType, ServerCreateRequest
from portico.services.server_service import (
    add_external_server,
    delete_all_servers_for_tenant,
    get_aggregated_tools,
    get_external_servers_with_auth,
    list_servers_for_tenant,
    remove_external_server,
)
from portico.storage.factory import get_server_repository


class TestServerService:
    """外部 MCP サーバー管理ロジックの単体テスト。"""

    @pytest.mark.asyncio
    async def test_list_servers_empty_when_no_external_servers(self):
        """外部サーバーが未登録の場合、空リストが返る。"""
        servers = await list_servers_for_tenant("tenant_empty")
        assert servers == []

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        """テナント A と テナント B の外部サーバーが相互に混ざらない。"""
        repo = get_server_repository()
        await repo.create_server(
            "tenant_a",
            {
                "id": "srv-1",
                "name": "Server A",
                "url": "https://a.mcp.example.com",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )
        await repo.create_server(
            "tenant_b",
            {
                "id": "srv-2",
                "name": "Server B",
                "url": "https://b.mcp.example.com",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )

        servers_a = await list_servers_for_tenant("tenant_a")
        server_names_a = [s["name"] for s in servers_a]
        assert "Server A" in server_names_a
        assert "Server B" not in server_names_a

        servers_b = await list_servers_for_tenant("tenant_b")
        server_names_b = [s["name"] for s in servers_b]
        assert "Server B" in server_names_b
        assert "Server A" not in server_names_b

    @pytest.mark.asyncio
    async def test_add_external_server_success(self):
        """外部サーバーの登録、プローブ判定が正常に行われる。"""

        async def mock_post(url, **kwargs):
            if "/sync" in str(url):
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"tools": []}})

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
            req = ServerCreateRequest(name="Jira MCP", url="https://jira.mcp.example.com")

            with patch("httpx.AsyncClient.post", side_effect=mock_post):
                res = await add_external_server(req, tenant_id="tenant_jira")

                assert res["name"] == "Jira MCP"
                assert res["url"] == "https://jira.mcp.example.com"
                assert res["status"] == "active"
                assert res["tenant_id"] == "tenant_jira"
                assert res["is_builtin"] is False

    @pytest.mark.asyncio
    async def test_add_external_server_infrastructure_limit(self):
        """物理リミット (MAX_SERVERS_PER_TENANT) 到達時に 429 エラーを送出する。"""
        with (
            patch("portico.services.server_service.MAX_SERVERS_PER_TENANT", 2),
            patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]),
        ):
            repo = get_server_repository()
            await repo.create_server(
                "tenant_limit_test",
                {
                    "id": "s-1",
                    "name": "S1",
                    "url": "http://s1",
                    "is_builtin": False,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            )
            await repo.create_server(
                "tenant_limit_test",
                {
                    "id": "s-2",
                    "name": "S2",
                    "url": "http://s2",
                    "is_builtin": False,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            )

            req = ServerCreateRequest(name="S3", url="https://s3.example.com")
            with pytest.raises(HTTPException) as exc_info:
                await add_external_server(req, tenant_id="tenant_limit_test")
            assert exc_info.value.status_code == 429
            assert "Tenant infrastructure limit reached" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_remove_external_server(self):
        """外部サーバーの削除テスト。"""
        repo = get_server_repository()
        await repo.create_server(
            "tenant_del",
            {
                "id": "srv-del",
                "name": "Delete Me",
                "url": "https://del.example.com",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )

        # 正常削除
        deleted = await remove_external_server("srv-del", "tenant_del")
        assert deleted is True
        assert await repo.get_server("tenant_del", "srv-del") is None

        # 存在しないサーバーの削除は False
        deleted_nonexist = await remove_external_server("srv-nonexist", "tenant_del")
        assert deleted_nonexist is False

    @pytest.mark.asyncio
    async def test_delete_all_servers_for_tenant(self):
        """テナント一括削除時に該当テナントのサーバーのみ削除される。"""
        repo = get_server_repository()
        await repo.create_server("tenant_x", {"id": "s1", "name": "S1", "url": "http://1", "created_at": "2026-01-01", "updated_at": "2026-01-01"})
        await repo.create_server("tenant_x", {"id": "s2", "name": "S2", "url": "http://2", "created_at": "2026-01-01", "updated_at": "2026-01-01"})
        await repo.create_server("tenant_y", {"id": "s3", "name": "S3", "url": "http://3", "created_at": "2026-01-01", "updated_at": "2026-01-01"})

        count = await delete_all_servers_for_tenant("tenant_x")
        assert count == 2
        assert await repo.get_server("tenant_x", "s1") is None
        assert await repo.get_server("tenant_x", "s2") is None
        assert await repo.get_server("tenant_y", "s3") is not None

    @pytest.mark.asyncio
    async def test_get_aggregated_tools(self):
        """標準ツールと外部 MCP サーバーのツールマニフェストがマージされる。"""
        repo = get_server_repository()
        await repo.create_server(
            "tenant_agg",
            {
                "id": "s-ext",
                "name": "External Tools",
                "url": "https://ext.example.com",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )

        mock_resp = httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": {"tools": [{"name": "custom_deploy_tool", "description": "Custom deployer", "parameters": {}}]},
            },
        )

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            tools = await get_aggregated_tools("tenant_agg")
            tool_names = [t["name"] for t in tools]
            orig_names = [t.get("original_name") for t in tools]
            # 外部ツールには名前空間プレフィックスが付与されること
            assert "external_tools__custom_deploy_tool" in tool_names
            assert "custom_deploy_tool" in orig_names

    @pytest.mark.asyncio
    async def test_namespaced_tools_collision_prevention(self):
        """同一ツール名を持つ2つの外部 MCP サーバーが登録された際、名前空間によって衝突せず共存できることを検証。"""
        repo = get_server_repository()
        await repo.create_server(
            "tenant_collision",
            {
                "id": "srv-slack",
                "name": "Slack MCP",
                "url": "https://slack.example.com",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )
        await repo.create_server(
            "tenant_collision",
            {
                "id": "srv-teams",
                "name": "Teams MCP",
                "url": "https://teams.example.com",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )

        async def mock_post_collision(url, **kwargs):
            host = urlparse(str(url)).hostname
            if host == "slack.example.com":
                return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"tools": [{"name": "send_message", "description": "Send via Slack"}]}})
            if host == "teams.example.com":
                return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"tools": [{"name": "send_message", "description": "Send via Teams"}]}})
            return httpx.Response(404)

        with patch("httpx.AsyncClient.post", side_effect=mock_post_collision):
            tools = await get_aggregated_tools("tenant_collision")
            tool_names = [t["name"] for t in tools]
            assert "slack_mcp__send_message" in tool_names
            assert "teams_mcp__send_message" in tool_names

            slack_tool = next(t for t in tools if t["name"] == "slack_mcp__send_message")
            teams_tool = next(t for t in tools if t["name"] == "teams_mcp__send_message")
            assert slack_tool["original_name"] == "send_message"
            assert slack_tool["server_name"] == "Slack MCP"
            assert slack_tool["description"] == "Send via Slack"
            assert teams_tool["original_name"] == "send_message"
            assert teams_tool["server_name"] == "Teams MCP"
            assert teams_tool["description"] == "Send via Teams"

    @pytest.mark.asyncio
    async def test_add_server_with_bearer_auth(self):
        """Bearer 認証付き外部サーバーの登録と暗号化保存を検証。"""
        import socket

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
            req = ServerCreateRequest(
                name="Secure Server",
                url="https://secure.example.com",
                auth_type=AuthType.BEARER,
                auth_token="jwt-secret-abc",
            )

            async def mock_post(url, **kwargs):
                if "/sync" in str(url):
                    return httpx.Response(200, json={"status": "ok"})
                return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"tools": []}})

            with patch("httpx.AsyncClient.post", side_effect=mock_post) as mock_p:
                server = await add_external_server(req, "tenant_auth")
                assert server["auth_type"] == "bearer"
                assert server["has_auth"] is True
                assert "jwt-secret-abc" not in str(server)

                # プローブ時に Authorization ヘッダーが付与されていること
                probe_call = mock_p.call_args_list[0]
                called_headers = probe_call[1].get("headers", {})
                assert called_headers.get("Authorization") == "Bearer jwt-secret-abc"

                # get_external_servers_with_auth で復号ヘッダーが取得できること
                servers_with_auth = await get_external_servers_with_auth("tenant_auth")
                target = next(s for s in servers_with_auth if s["url"] == "https://secure.example.com")
                assert target["headers"] == {"Authorization": "Bearer jwt-secret-abc"}
