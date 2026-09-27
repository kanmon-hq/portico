"""
Tests for dynamic multi-tenant MCP SSE protocol handlers and context resolution.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from portico.core.fastmcp_hub import (
    dynamic_call_tool,
    dynamic_list_tools,
    get_current_mcp_context,
    request_ctx,
)


@pytest.mark.asyncio
async def test_dynamic_list_tools_returns_empty_when_no_servers():
    """外部サーバー未登録時は空のツールリストが返却されることを検証。"""
    tools = await dynamic_list_tools()
    assert isinstance(tools, list)
    assert len(tools) == 0


@pytest.mark.asyncio
async def test_dynamic_list_tools_with_aggregated_tools():
    """ツール一覧の取得および JSON Schema への正常な変換検証"""
    mock_tools = [
        {
            "name": "tool_standard",
            "description": "Standard Tool",
            "params_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "scopes": ["tools:read"],
        },
        {
            "name": "tool_shorthand",
            "description": "Shorthand Tool",
            "params_schema": {"count": "integer", "config": {"type": "object"}},
            "scopes": ["tools:write"],
        },
        {
            "name": "tool_empty_schema",
            "description": "Empty Schema Tool",
            "params_schema": None,
            "scopes": [],
        },
    ]

    with patch("portico.services.server_service.get_aggregated_tools", new_callable=AsyncMock) as mock_get_tools:
        mock_get_tools.return_value = mock_tools
        tools = await dynamic_list_tools()
        assert len(tools) == 3
        assert tools[0].name == "tool_standard"
        assert tools[0].inputSchema["type"] == "object"
        assert tools[1].name == "tool_shorthand"
        assert "count" in tools[1].inputSchema["properties"]
        assert tools[2].name == "tool_empty_schema"


@pytest.mark.asyncio
async def test_dynamic_call_tool_unknown():
    """存在しないツールの呼び出し時にエラーメッセージが返却されることを検証。"""
    contents = await dynamic_call_tool(
        name="completely_unknown_tool",
        arguments={},
    )
    assert isinstance(contents, list)
    assert len(contents) == 1
    assert "Error:" in contents[0].text or "404" in contents[0].text


@pytest.mark.asyncio
async def test_dynamic_call_tool_success():
    """ツールのディスパッチ成功時に TextContent が正常に返却される検証"""
    with patch("portico.services.server_service.dispatch_tool_call", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {"result": "success", "count": 42}
        contents = await dynamic_call_tool(name="calc_add", arguments={"a": 1, "b": 2})
        assert len(contents) == 1
        assert contents[0].type == "text"
        assert '"result": "success"' in contents[0].text


@pytest.mark.asyncio
async def test_dynamic_call_tool_unexpected_exception():
    """ツール呼び出し時に予期せぬ例外が発生した際のエラーハンドリング検証"""
    with patch("portico.services.server_service.dispatch_tool_call", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.side_effect = RuntimeError("Fatal hardware failure")
        contents = await dynamic_call_tool(name="failing_tool", arguments={})
        assert len(contents) == 1
        assert contents[0].text == "Internal Server Error"


def test_get_current_mcp_context_from_request():
    """FastMCP リクエストコンテキストからのヘッダー・クエリ情報抽出検証"""
    # 1. 正常なコンテキスト抽出
    scope = {
        "type": "http",
        "headers": [
            (b"x-tenant-id", b"tenant_mcp_1"),
            (b"x-key-id", b"key_123"),
            (b"x-key-prefix", b"pk_live"),
            (b"x-service-id", b"svc_agent"),
            (b"x-scopes", b"read,write"),
        ],
        "query_string": b"",
    }
    req = Request(scope)
    mock_ctx = MagicMock()
    mock_ctx.request = req

    token = request_ctx.set(mock_ctx)
    try:
        tenant_id, scopes, context = get_current_mcp_context()
        assert tenant_id == "tenant_mcp_1"
        assert scopes == ["read", "write"]
        assert context.key_id == "key_123"
        assert context.is_proxied is True
    finally:
        request_ctx.reset(token)


def test_get_current_mcp_context_tenant_conflict():
    """テナントコンフリクト発生時に 403 Forbidden となること"""
    scope = {
        "type": "http",
        "headers": [(b"x-tenant-id", b"tenant_A")],
        "query_string": b"tenant_id=tenant_B",
    }
    req = Request(scope)
    mock_ctx = MagicMock()
    mock_ctx.request = req

    token = request_ctx.set(mock_ctx)
    try:
        with pytest.raises(HTTPException) as exc_info:
            get_current_mcp_context()
        assert exc_info.value.status_code == 403
    finally:
        request_ctx.reset(token)
