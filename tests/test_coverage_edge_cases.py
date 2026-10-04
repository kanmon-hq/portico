"""
Additional unit tests targeting 100% coverage across edge cases, fail-fast configurations, and fallbacks.
"""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from portico.api.deps import verify_gateway_secret
from portico.cache.valkey_cache import ValkeyCache
from portico.core.config import validate_gateway_auth_config
from portico.services.audit import log_tool_execution
from portico.services.crypto import (
    _get_key,
    decrypt_auth_config,
    decrypt_secret,
    validate_crypto_config,
)
from portico.services.server_service import dispatch_tool_call
from portico.storage.sqlite import SQLiteServerRepository


def test_verify_gateway_secret_variations(monkeypatch):
    """verify_gateway_secret の全パターン検証"""
    monkeypatch.setattr("portico.api.deps.INSECURE_NO_GATEWAY_AUTH", False)

    # 有効なシークレットが設定されていない場合
    monkeypatch.setattr("portico.api.deps.get_valid_gateway_secrets", lambda: [])
    assert verify_gateway_secret("any-secret") is False

    # シークレットが設定されている場合
    monkeypatch.setattr("portico.api.deps.get_valid_gateway_secrets", lambda: ["secret-1", "secret-2"])
    assert verify_gateway_secret(None) is False
    assert verify_gateway_secret("") is False
    assert verify_gateway_secret("invalid-secret") is False
    assert verify_gateway_secret("secret-1") is True
    assert verify_gateway_secret("secret-2") is True
    assert verify_gateway_secret("Bearer secret-1") is True
    assert verify_gateway_secret("bearer  secret-2 ") is True


# ── 2. core/config.py Fail-Fast validations ─────────────────────────────────


def test_validate_gateway_auth_config_production_fail_fast(monkeypatch):
    """本番環境で GATEWAY_SHARED_SECRET 未設定時は Fail-Fast エラーとなること"""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr("portico.core.config.ENVIRONMENT", "production")
    monkeypatch.setattr("portico.core.config.INSECURE_NO_GATEWAY_AUTH", False)
    monkeypatch.setattr("portico.core.config.GATEWAY_SHARED_SECRET", None)

    with pytest.raises(RuntimeError, match="GATEWAY_SHARED_SECRET must be set in production"):
        validate_gateway_auth_config()

    # 設定済みの場合は通過
    monkeypatch.setattr("portico.core.config.GATEWAY_SHARED_SECRET", "valid_secret_32_chars_long_1234567890")
    validate_gateway_auth_config()


# ── 3. services/crypto.py Fail-Fast & decryption errors ─────────────────────


def test_validate_crypto_config_production_fail_fast(monkeypatch):
    """本番環境で SECRET_ENCRYPTION_KEY 未設定時は Fail-Fast エラーとなること"""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SECRET_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_ENCRYPTION_KEY must be set in production environment"):
        validate_crypto_config()

    # 開発環境（既定）では自動生成され通過
    monkeypatch.setenv("ENVIRONMENT", "development")
    validate_crypto_config()


def test_tool_definition_schema():
    """ToolDefinition スキーマのバリデーションとパラメータ同期検証"""
    from portico.schemas.tools import ToolDefinition, ToolExecutionResponse

    tool = ToolDefinition(
        name="test_tool",
        description="Demo",
        params_schema={"type": "object"},
        scopes=["read"],
    )
    assert tool.parameters == {"type": "object"}
    assert tool.params_schema == {"type": "object"}

    resp = ToolExecutionResponse(tool="test_tool", result={"status": "ok"})
    assert resp.tool == "test_tool"
    assert resp.result == {"status": "ok"}


def test_crypto_decryption_failures():
    """不正な暗号文または無効な Base64 文字列の復号時エラーハンドリング"""
    assert decrypt_secret("") == ""
    assert decrypt_secret("raw_unencrypted_text") == "raw_unencrypted_text"

    with pytest.raises(ValueError, match="Invalid encrypted secret format"):
        decrypt_secret("enc:v1:invalid_without_colon")

    # decrypt_auth_config の破損データハンドリング
    assert decrypt_auth_config("enc:v1:invalid:broken") == {}
    assert decrypt_auth_config(None) == {}

    # _get_key の 32 バイト鍵
    k32 = b"12345678901234567890123456789012"
    assert _get_key(k32) == k32


# ── 4. services/audit.py ────────────────────────────────────────────────────


def test_audit_log_security_event():
    """監査ログのセキュリティイベント出力が例外なく実行されること"""
    rec = log_tool_execution(
        tool_name="test_tool",
        duration_ms=12.34,
        success=True,
        error_message=None,
        extra={"custom": "data"},
    )
    assert rec["extra"]["custom"] == "data"


# ── 5. services/url_validator.py DNS resolution failures ────────────────────


def test_url_validator_dns_error():
    """DNS 解決失敗 (socket.gaierror) 時の適切なバリデーション拒絶"""
    from portico.services.url_validator import SSRFValidationError, validate_mcp_url

    with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")), pytest.raises(SSRFValidationError, match="Could not resolve hostname"):
        validate_mcp_url("https://nonexistent.domain.invalid/mcp")


# ── 6. storage/sqlite.py non-JSON comma-separated scopes fallback ────────────


@pytest.mark.asyncio
async def test_sqlite_comma_separated_scopes_fallback(tmp_path):
    """SQLite の scopes カラムが JSON ではなくカンマ区切り文字列だった場合のフォールバック"""
    db_file = str(tmp_path / "test_legacy_scopes.db")
    repo = SQLiteServerRepository(db_path=db_file)
    await repo.init_storage()

    conn = await repo._get_conn()
    await conn.execute(
        """
        INSERT INTO portico_custom_servers (
            id, tenant_id, name, url, status, auth_type, scopes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            "srv-legacy",
            "tenant_legacy",
            "Legacy Server",
            "https://legacy.example.com",
            "active",
            "none",
            "read, write, admin",  # カンマ区切り文字列
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    await conn.commit()

    server = await repo.get_server("tenant_legacy", "srv-legacy")
    assert server is not None
    assert server["scopes"] == ["read", "write", "admin"]
    await repo.close()


# ── 7. services/server_service.py dispatch error handling ───────────────────


@pytest.mark.asyncio
async def test_dispatch_tool_call_external_server_errors():
    """外部 MCP サーバー通信時の JSON-RPC エラーや 502 Bad Gateway ハンドリング"""
    repo = SQLiteServerRepository(db_path=":memory:")
    await repo.init_storage()
    await repo.create_server(
        "tenant_rpc_err",
        {
            "id": "srv-err",
            "name": "Error MCP",
            "url": "https://error.example.com",
            "status": "active",
            "scopes": ["all"],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )

    with patch("portico.services.server_service.get_server_repository", return_value=repo):
        # 1. 外部サーバーが JSON-RPC error を返却した場合
        mock_err_resp = httpx.Response(200, json={"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}})
        with patch("httpx.AsyncClient.post", return_value=mock_err_resp):
            with pytest.raises(Exception) as exc_info:
                await dispatch_tool_call("error_mcp__do_fail", {}, tenant_id="tenant_rpc_err")
            assert "502" in str(exc_info.value) or "error" in str(exc_info.value).lower()

        # 2. 外部サーバー通信で例外が発生した場合
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectTimeout("Connection timed out")):
            with pytest.raises(Exception) as exc_info:
                await dispatch_tool_call("error_mcp__do_timeout", {}, tenant_id="tenant_rpc_err")
            assert "502" in str(exc_info.value) or "Failed to communicate" in str(exc_info.value)

    await repo.close()


# ── 8. cache/valkey_cache.py connection failure & exception handling ─────────


@pytest.mark.asyncio
async def test_valkey_cache_exceptions_handling():
    """ValkeyCache の set / delete / clear で例外発生時に安全に処理されること"""
    cache = ValkeyCache(url="redis://localhost:6379/0")
    mock_redis = AsyncMock()
    cache._redis = mock_redis

    mock_redis.set.side_effect = Exception("Write error")
    mock_redis.delete.side_effect = Exception("Delete error")
    mock_redis.flushdb.side_effect = Exception("Flush error")

    # 例外がスローされず安全に None/何もしないこと
    await cache.set("k", "v")
    await cache.delete("k")
    await cache.clear()

    # Redis 未接続時の動作
    cache_disconnected = ValkeyCache()
    cache_disconnected._redis = None
    with patch.object(cache_disconnected, "_get_redis", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        assert await cache_disconnected.get("k") is None
        await cache_disconnected.set("k", "v")
        await cache_disconnected.delete("k")
        await cache_disconnected.delete_prefix("k:")
        await cache_disconnected.clear()
