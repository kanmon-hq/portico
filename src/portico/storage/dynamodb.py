"""
AWS DynamoDB ストレージリポジトリ実装 (Kura 互換 1テーブル設計)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from portico.core.config import AWS_REGION, DYNAMODB_ENDPOINT, DYNAMODB_TABLE_NAME
from portico.storage.base import BaseServerRepository

logger = logging.getLogger(__name__)


class DynamoDBServerRepository(BaseServerRepository):
    """DynamoDB (PK: TENANT#<tenant_id>, SK: SERVER#<server_id>) をバックエンドとするサーバーリポジトリ"""

    def __init__(
        self,
        table_name: str = DYNAMODB_TABLE_NAME,
        region_name: str = AWS_REGION,
        endpoint_url: str | None = DYNAMODB_ENDPOINT,
    ):
        self.table_name = table_name
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self._dynamodb = None
        self._table = None

    def _get_resource(self):
        if self._dynamodb is None:
            try:
                import boto3

                self._dynamodb = boto3.resource(
                    "dynamodb",
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                )
            except ImportError as exc:
                raise RuntimeError("boto3 is required to use DynamoDB storage backend. Install via: pip install 'portico[dynamodb]' (or uv add 'portico[dynamodb]')") from exc
        return self._dynamodb

    def _get_table(self):
        if self._table is None:
            dynamodb = self._get_resource()
            self._table = dynamodb.Table(self.table_name)
        return self._table

    async def init_storage(self) -> None:
        table = self._get_table()

        # Verify table connectivity / auto-create if not existing (e.g. DynamoDB Local)
        def _check_or_create():
            try:
                _ = table.table_status
                logger.info("⚡ DynamoDB Storage connected to table '%s'", self.table_name)
            except Exception as exc:
                # Check for ResourceNotFoundException
                exc_name = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
                if exc_name == "ResourceNotFoundException" or "ResourceNotFoundException" in str(exc):
                    logger.info("⚡ DynamoDB table '%s' not found. Creating table...", self.table_name)
                    dynamodb = self._get_resource()
                    new_table = dynamodb.create_table(
                        TableName=self.table_name,
                        KeySchema=[
                            {"AttributeName": "PK", "KeyType": "HASH"},
                            {"AttributeName": "SK", "KeyType": "RANGE"},
                        ],
                        AttributeDefinitions=[
                            {"AttributeName": "PK", "AttributeType": "S"},
                            {"AttributeName": "SK", "AttributeType": "S"},
                        ],
                        BillingMode="PAY_PER_REQUEST",
                    )
                    new_table.wait_until_exists()
                    self._table = new_table
                    logger.info("⚡ DynamoDB table '%s' created successfully.", self.table_name)
                else:
                    logger.warning("⚠️ DynamoDB table verification check: %s", exc)

        await asyncio.to_thread(_check_or_create)

    async def close(self) -> None:
        self._table = None
        self._dynamodb = None

    def _item_to_server(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
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
        table = self._get_table()
        pk = f"TENANT#{tenant_id}"

        def _query():
            from boto3.dynamodb.conditions import Key

            resp = table.query(KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("SERVER#"))
            return resp.get("Items", [])

        items = await asyncio.to_thread(_query)
        return [self._item_to_server(item) for item in items]

    async def get_server(self, tenant_id: str, server_id: str) -> dict[str, Any] | None:
        table = self._get_table()
        pk = f"TENANT#{tenant_id}"
        sk = f"SERVER#{server_id}"

        def _get():
            resp = table.get_item(Key={"PK": pk, "SK": sk})
            return resp.get("Item")

        item = await asyncio.to_thread(_get)
        if item:
            return self._item_to_server(item)
        return None

    async def create_server(self, tenant_id: str, server_data: dict[str, Any]) -> dict[str, Any]:
        table = self._get_table()
        server_id = server_data["id"]
        pk = f"TENANT#{tenant_id}"
        sk = f"SERVER#{server_id}"

        item = {
            "PK": pk,
            "SK": sk,
            "id": server_id,
            "tenant_id": tenant_id,
            "name": server_data["name"],
            "url": server_data["url"],
            "status": server_data.get("status", "active"),
            "auth_type": server_data.get("auth_type", "none"),
            "encrypted_auth_config": server_data.get("encrypted_auth_config"),
            "scopes": set(server_data.get("scopes", [])) if server_data.get("scopes") else set(),
            "created_at": server_data["created_at"],
            "updated_at": server_data["updated_at"],
        }

        await asyncio.to_thread(lambda: table.put_item(Item=item))
        return await self.get_server(tenant_id, server_id) or server_data

    async def update_server(self, tenant_id: str, server_id: str, update_data: dict[str, Any]) -> dict[str, Any] | None:
        curr = await self.get_server(tenant_id, server_id)
        if not curr:
            return None
        curr.update(update_data)
        return await self.create_server(tenant_id, curr)

    async def delete_server(self, tenant_id: str, server_id: str) -> bool:
        table = self._get_table()
        pk = f"TENANT#{tenant_id}"
        sk = f"SERVER#{server_id}"

        await asyncio.to_thread(lambda: table.delete_item(Key={"PK": pk, "SK": sk}))
        return True
