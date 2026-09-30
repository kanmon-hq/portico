"""
Azure Cosmos DB ストレージリポジトリ実装 (SQL API)
"""

from __future__ import annotations

import logging
from typing import Any

from portico.core.config import (
    COSMOSDB_CONTAINER,
    COSMOSDB_DATABASE,
    COSMOSDB_ENDPOINT,
    COSMOSDB_KEY,
)
from portico.storage.base import BaseServerRepository

logger = logging.getLogger(__name__)


class CosmosDBServerRepository(BaseServerRepository):
    """Azure Cosmos DB をバックエンドとするサーバーリポジトリ"""

    def __init__(
        self,
        endpoint: str | None = COSMOSDB_ENDPOINT,
        key: str | None = COSMOSDB_KEY,
        database_name: str = COSMOSDB_DATABASE,
        container_name: str = COSMOSDB_CONTAINER,
    ):
        self.endpoint = endpoint
        self.key = key
        self.database_name = database_name
        self.container_name = container_name
        self._container = None

    def _get_container(self):
        if self._container is None:
            try:
                from azure.cosmos.aio import CosmosClient

                client = CosmosClient(self.endpoint, credential=self.key)
                database = client.get_database_client(self.database_name)
                self._container = database.get_container_client(self.container_name)
            except ImportError as exc:
                raise RuntimeError("azure-cosmos is required to use Cosmos DB storage backend. Install via: pip install 'portico[cosmos]' (or uv add 'portico[cosmos]')") from exc
        return self._container

    async def init_storage(self) -> None:
        logger.info("🪐 Cosmos DB Storage initialized on container '%s'", self.container_name)

    async def close(self) -> None:
        self._container = None

    def _item_to_dict(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("server_id") or item.get("id"),
            "tenant_id": item.get("tenant_id"),
            "name": item.get("name"),
            "url": item.get("url"),
            "status": item.get("status", "active"),
            "auth_type": item.get("auth_type", "none"),
            "encrypted_auth_config": item.get("encrypted_auth_config"),
            "scopes": list(item.get("scopes", [])),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }

    async def list_servers(self, tenant_id: str) -> list[dict[str, Any]]:
        container = self._get_container()
        query = "SELECT * FROM c WHERE c.tenant_id = @tenant_id"
        parameters = [{"name": "@tenant_id", "value": tenant_id}]
        items = [item async for item in container.query_items(query=query, parameters=parameters, partition_key=tenant_id)]
        return [self._item_to_dict(it) for it in items]

    async def get_server(self, tenant_id: str, server_id: str) -> dict[str, Any] | None:
        container = self._get_container()
        doc_id = f"{tenant_id}_{server_id}"
        try:
            item = await container.read_item(item=doc_id, partition_key=tenant_id)
            return self._item_to_dict(item)
        except Exception:
            return None

    async def create_server(self, tenant_id: str, server_data: dict[str, Any]) -> dict[str, Any]:
        container = self._get_container()
        server_id = server_data["id"]
        doc_id = f"{tenant_id}_{server_id}"

        item = dict(server_data)
        item["id"] = doc_id
        item["server_id"] = server_id
        item["tenant_id"] = tenant_id

        created = await container.upsert_item(item)
        return self._item_to_dict(created)

    async def update_server(self, tenant_id: str, server_id: str, update_data: dict[str, Any]) -> dict[str, Any] | None:
        curr = await self.get_server(tenant_id, server_id)
        if not curr:
            return None
        curr.update(update_data)
        return await self.create_server(tenant_id, curr)

    async def delete_server(self, tenant_id: str, server_id: str) -> bool:
        container = self._get_container()
        doc_id = f"{tenant_id}_{server_id}"
        try:
            await container.delete_item(item=doc_id, partition_key=tenant_id)
            return True
        except Exception:
            return False
