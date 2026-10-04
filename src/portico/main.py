"""
Portico — MCP Gateway (Integration Hub)
FastAPI アプリケーション エントリポイント
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from portico.api.router import gateway_router
from portico.core.config import (
    DOCS_PATH,
    LOG_LEVEL,
    OPENAPI_PATH,
    REDOC_URL,
    ROOT_PATH,
    SCALAR_URL,
    validate_gateway_auth_config,
)
from portico.core.fastmcp_hub import gateway_mcp
from portico.schemas.error import ErrorResponse, HTTPValidationError
from portico.services.crypto import validate_crypto_config
from portico.storage.factory import close_storage, init_storage

load_dotenv()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Portico 起動時のリソース初期化（ストレージ初期化）とクリーンアップ。"""
    logger.info("🚀 Starting Portico — MCP Gateway")
    validate_crypto_config()
    validate_gateway_auth_config()
    await init_storage()
    yield
    logger.info("🛑 Shutting down Portico")
    await close_storage()


COMMON_RESPONSES = {
    401: {"model": ErrorResponse, "description": "API キーが無効または未指定"},
    403: {"model": ErrorResponse, "description": "アクセス権限不足 (管理者またはテナント権限不足)"},
    404: {
        "model": ErrorResponse,
        "description": "指定されたツールまたはリソースが存在しない、または非公開 API へのアクセス遮断",
    },
    422: {"model": HTTPValidationError, "description": "リクエストパラメータまたはボディのバリデーションエラー"},
    429: {"model": ErrorResponse, "description": "レートリミットまたは実行回数上限到達"},
    500: {"model": ErrorResponse, "description": "サーバー内部エラー"},
    502: {"model": ErrorResponse, "description": "外部 MCP サーバーまたは SaaS への接続エラー"},
    504: {"model": ErrorResponse, "description": "外部 MCP サーバーからの応答タイムアウト"},
}


def _resolve_url(url: str | None) -> str | None:
    if url is None:
        return None
    cleaned = url.strip()
    if cleaned.lower() in ("", "none", "false", "null"):
        return None
    return cleaned


resolved_openapi_url = _resolve_url(OPENAPI_PATH)
resolved_scalar_url = _resolve_url(SCALAR_URL)

app = FastAPI(
    title="Portico — MCP Gateway",
    description="SaaS ツール連携および外部 MCP サーバーの統合ハブ・実行ゲートウェイ。",
    version="0.1.0",
    root_path=ROOT_PATH,
    lifespan=lifespan,
    docs_url=_resolve_url(DOCS_PATH),
    redoc_url=_resolve_url(REDOC_URL),
    openapi_url=resolved_openapi_url,
    responses=COMMON_RESPONSES,
)


if resolved_scalar_url and resolved_openapi_url:

    @app.get(resolved_scalar_url, include_in_schema=False)
    async def scalar_docs() -> HTMLResponse:
        """Scalar API Reference ドキュメント UI を返却"""
        spec_url = f"{ROOT_PATH.rstrip('/')}{resolved_openapi_url}" if ROOT_PATH and ROOT_PATH != "/" and not resolved_openapi_url.startswith("http") else resolved_openapi_url
        html = f"""<!doctype html>
<html>
  <head>
    <title>Portico — API Reference</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script
      id="api-reference"
      type="application/json"
      data-url="{spec_url}">
    </script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>
"""
        return HTMLResponse(content=html)


# ── Include REST APIs & Internal Routes ──────────────────────────────
app.include_router(gateway_router)


# ── Mount FastMCP SSE handler under /v1 (SSE at /v1/sse) ──
mcp_asgi = gateway_mcp.http_app(transport="sse")
app.mount("/v1", mcp_asgi)
