"""
SQLite ストレージリポジトリ実装 (aiosqlite)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from portico.core.config import SQLITE_PATH
from portico.storage.base import BaseServerRepository

logger = logging.getLogger(__name__)


class SQLiteServerRepository(BaseServerRepository):
    """SQLite をバックエンドとするカスタムサーバーリポジトリ"""

    def __init__(self, db_path: str = SQLITE_PATH):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._create_tables()
        return self._db

    async def _create_tables(self) -> None:
        if self._db is None:
            return
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS portico_custom_servers (
                id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                auth_type TEXT NOT NULL DEFAULT 'none',
                encrypted_auth_config TEXT,
                scopes TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, id)
            );
        """)
        await self._db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_portico_custom_servers_tenant_url
            ON portico_custom_servers (tenant_id, url);
        """)
        await self._db.commit()

    async def init_storage(self) -> None:
        await self._get_conn()
        await self._create_tables()
        logger.info("📁 SQLite Storage initialized at '%s'", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        d = dict(row)
        scopes_raw = d.get("scopes", "[]")
        if isinstance(scopes_raw, str):
            try:
                d["scopes"] = json.loads(scopes_raw)
            except Exception:
                d["scopes"] = [s.strip() for s in scopes_raw.split(",") if s.strip()]
        return d

    async def list_servers(self, tenant_id: str) -> list[dict[str, Any]]:
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT id, tenant_id, name, url, status, auth_type, encrypted_auth_config, scopes, created_at, updated_at
            FROM portico_custom_servers
            WHERE tenant_id = ?
            ORDER BY created_at ASC;
            """,
            (tenant_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_dict(r) for r in rows]

    async def get_server(self, tenant_id: str, server_id: str) -> dict[str, Any] | None:
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT id, tenant_id, name, url, status, auth_type, encrypted_auth_config, scopes, created_at, updated_at
            FROM portico_custom_servers
            WHERE tenant_id = ? AND id = ?;
            """,
            (tenant_id, server_id),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    async def create_server(self, tenant_id: str, server_data: dict[str, Any]) -> dict[str, Any]:
        conn = await self._get_conn()
        scopes_json = json.dumps(server_data.get("scopes", []))
        await conn.execute(
            """
            INSERT INTO portico_custom_servers (
                id, tenant_id, name, url, status, auth_type, encrypted_auth_config, scopes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                server_data["id"],
                tenant_id,
                server_data["name"],
                server_data["url"],
                server_data.get("status", "active"),
                server_data.get("auth_type", "none"),
                server_data.get("encrypted_auth_config"),
                scopes_json,
                server_data["created_at"],
                server_data["updated_at"],
            ),
        )
        await conn.commit()
        return await self.get_server(tenant_id, server_data["id"]) or server_data

    async def update_server(self, tenant_id: str, server_id: str, update_data: dict[str, Any]) -> dict[str, Any] | None:
        conn = await self._get_conn()
        fields = []
        values = []
        for k, v in update_data.items():
            if k == "scopes":
                fields.append("scopes = ?")
                values.append(json.dumps(v))
            else:
                fields.append(f"{k} = ?")
                values.append(v)
        if not fields:
            return await self.get_server(tenant_id, server_id)

        values.extend([tenant_id, server_id])
        query = f"UPDATE portico_custom_servers SET {', '.join(fields)} WHERE tenant_id = ? AND id = ?"
        await conn.execute(query, tuple(values))
        await conn.commit()
        return await self.get_server(tenant_id, server_id)

    async def delete_server(self, tenant_id: str, server_id: str) -> bool:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "DELETE FROM portico_custom_servers WHERE tenant_id = ? AND id = ?",
            (tenant_id, server_id),
        )
        await conn.commit()
        return cursor.rowcount > 0
