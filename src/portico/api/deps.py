"""
MCP Gateway — 依存性注入 (DI) モジュール
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from portico.core.config import (
    DEFAULT_TENANT_ID,
    GATEWAY_SECRET_HEADER,
    INSECURE_NO_GATEWAY_AUTH,
    INTERNAL_API_KEY,
    get_valid_gateway_secrets,
)
from portico.schemas.context import RequestContext

internal_bearer = HTTPBearer(auto_error=False)


def verify_gateway_secret(secret_value: str | None) -> bool:
    """
    Gateway 共有シークレット (X-Gateway-Secret または Bearer トークン) を検証する。
    INSECURE_NO_GATEWAY_AUTH=true の場合は常に True。
    新旧シークレット (ローテーション対応) のいずれかに一致すれば True を返す。
    """
    if INSECURE_NO_GATEWAY_AUTH:
        return True

    valid_secrets = get_valid_gateway_secrets()
    if not valid_secrets:
        return False

    if not secret_value:
        return False

    # "Bearer <token>" 形式にも対応
    token = secret_value.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    return any(secrets.compare_digest(token, s) for s in valid_secrets)


def get_request_context(
    x_gateway_secret: str | None = Header(None, alias="X-Gateway-Secret"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_key_id: str | None = Header(None, alias="X-Key-ID"),
    x_key_prefix: str | None = Header(None, alias="X-Key-Prefix"),
    x_service_id: str | None = Header(None, alias="X-Service-ID"),
    tenant_id: str | None = Query(None),
) -> RequestContext:
    """
    Kura 仕様に準拠した Gateway リクエストコンテキスト解決 & 共有シークレット検証。
    - クライアント指定の tenant_id とプロキシ指定の X-Tenant-ID に不一致がある場合は 403 Forbidden (Fail-Fast)。
    - X-Gateway-Secret または Authorization ヘッダーによりゲートウェイ共有シークレットを検証。
    - INSECURE_NO_GATEWAY_AUTH=true 時はシークレット検証をバイパス。
    """
    # 1. テナントコンフリクトの検証 (Fail-Fast)
    if x_tenant_id and tenant_id and x_tenant_id.strip() != tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant ID conflict: Header X-Tenant-ID does not match query tenant_id",
        )

    # 2. Gateway 共有シークレットの検証 (Kura 準拠)
    secret_candidate = x_gateway_secret or authorization
    if not INSECURE_NO_GATEWAY_AUTH and not verify_gateway_secret(secret_candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized: Missing or invalid gateway shared secret ({GATEWAY_SECRET_HEADER})",
        )

    resolved_tenant = (x_tenant_id or tenant_id or DEFAULT_TENANT_ID).strip()
    is_proxied = bool(x_tenant_id and x_key_id)

    return RequestContext(
        tenant_id=resolved_tenant,
        key_id=x_key_id,
        key_prefix=x_key_prefix,
        service_id=x_service_id,
        is_proxied=is_proxied,
    )


def get_tenant_id(
    ctx: RequestContext = Depends(get_request_context),
) -> str:
    """リクエストコンテキストからテナントIDを解決する（後方互換性用）。"""
    return ctx.tenant_id


def require_internal_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(internal_bearer),
) -> str:
    """内部専用エンドポイントの Bearer トークン (INTERNAL_API_KEY) を検証する。"""
    if not INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Internal API is disabled: INTERNAL_API_KEY is not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid Authorization Bearer header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not secrets.compare_digest(credentials.credentials, INTERNAL_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Invalid internal API key",
        )
    return credentials.credentials


def get_scopes(
    x_scopes: str | None = Header(None, alias="X-Scopes"),
    x_scope: str | None = Header(None, alias="X-Scope"),
) -> list[str] | None:
    """
    リクエストヘッダーからクライアントの認可スコープ一覧を取得する。
    カンマ区切りまたはスペース区切りに対応。
    ヘッダーが存在しない場合は None を返す (未制限モード)。
    """
    raw = x_scopes or x_scope
    if raw is None:
        return None

    scopes: list[str] = []
    for chunk in raw.replace(",", " ").split():
        s = chunk.strip()
        if s and s not in scopes:
            scopes.append(s)
    return scopes
