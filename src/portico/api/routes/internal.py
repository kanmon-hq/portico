"""
MCP Gateway — 内部サービス間専用ルート
外部ロードバランサー (Nginx / ALB) で 404 遮断される非公開 API。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from portico.api.deps import require_internal_api_key
from portico.schemas.server import TenantCleanupResponse
from portico.services.server_service import delete_all_servers_for_tenant

router = APIRouter(
    prefix="",
    tags=["internal"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.delete("/tenants/{tenant_id}", response_model=TenantCleanupResponse)
async def delete_all_servers(tenant_id: str):
    """
    テナント削除時に呼ばれる内部専用 API。指定テナントの外部 MCP サーバーを全削除する。
    Authorization: Bearer <INTERNAL_API_KEY> 認証必須。
    """
    count = await delete_all_servers_for_tenant(tenant_id)
    return TenantCleanupResponse(status="success", tenant_id=tenant_id, deleted_count=count)
