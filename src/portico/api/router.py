"""
MCP Gateway — API ルーター統合モジュール
新統一パス体系:
- サービス提供用: /api/v1/mcp/...
- 内部サービス専用: /api/v1/mcp/internal/...
- ヘルスチェック: /api/mcp/health, /api/health
"""

from __future__ import annotations

from fastapi import APIRouter

from portico.api.routes import internal, ops, servers

gateway_router = APIRouter()

# システム系ルート (/health, /livez, /readyz, /metrics)
gateway_router.include_router(ops.router)

# 内部専用非公開ルート (/v1/internal/*)
internal_router = APIRouter(prefix="/v1/internal")
internal_router.include_router(internal.router)
gateway_router.include_router(internal_router)

# 外部サービス提供用 v1 API ルート (/v1/*)
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(servers.router)
gateway_router.include_router(v1_router)
