"""
MCP Gateway — 運用 & ヘルスチェックルート
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from portico.core.config import MOCK_EXTERNAL_APIS

router = APIRouter(tags=["ops"])


class GatewayHealthResponse(BaseModel):
    status: str = Field("ok", description="サービス稼働ステータス")
    service: str = Field("portico", description="サービス識別子")
    mock: bool = Field(..., description="モック外部 API 有効フラグ")


class ProbeResponse(BaseModel):
    status: str = Field("ok", description="プローブステータス")


@router.get("/health", response_model=GatewayHealthResponse)
async def health():
    """サービス全体の基本ヘルスチェック"""
    return GatewayHealthResponse(status="ok", service="portico", mock=MOCK_EXTERNAL_APIS)


@router.get("/livez", response_model=ProbeResponse)
async def liveness():
    """Liveness probe (コンテナ稼働確認)"""
    return ProbeResponse(status="ok")


@router.get("/readyz", response_model=ProbeResponse)
async def readiness():
    """Readiness probe (リクエスト受付可能確認)"""
    return ProbeResponse(status="ok")


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus 互換メトリクスエンドポイント"""
    return "# HELP portico_up Process availability\n# TYPE portico_up gauge\nportico_up 1\n"
