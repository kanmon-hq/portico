"""
Google Cloud Firestore ストレージリポジトリ実装
"""

from __future__ import annotations

import logging
from typing import Any

from portico.core.config import FIRESTORE_COLLECTION, FIRESTORE_PROJECT_ID
from portico.storage.base import BaseServerRepository

logger = logging.getLogger(__name__)


class FirestoreServerRepository(BaseServerRepository):
    """GCP Cloud Firestore をバックエンドとするサーバーリポジトリ"""

    def __init__(self, collection_name: str = FIRESTORE_COLLECTION, project_id: str | None = FIRESTORE_PROJECT_ID):
        self.collection_name = collection_name
        self.project_id = project_id
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from google.cloud import firestore

                self._client = firestore.AsyncClient(project=self.project_id)
            except ImportError as exc:
                raise RuntimeError("google-cloud-firestore is required to use Firestore storage backend. Install via: pip install 'portico[firestore]' (or uv add 'portico[firestore]')") from exc
        return self._client

    async def init_storage(self) -> None:
        logger.info("🔥 Firestore Storage initialized on collection '%s'", self.collection_name)

    async def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def _doc_to_dict(self, doc_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": doc_data.get("id"),
            "tenant_id": doc_data.get("tenant_id"),
            "name": doc_data.get("name"),
            "url": doc_data.get("url"),
            "status": doc_data.get("status", "active"),
            "auth_type": doc_data.get("auth_type", "none"),
            "encrypted_auth_config": doc_data.get("encrypted_auth_config"),
            "scopes": list(doc_data.get("scopes", [])),
            "created_at": str(doc_data.get("created_at")),
            "updated_at": str(doc_data.get("updated_at")),
        }

    async def list_servers(self, tenant_id: str) -> list[dict[str, Any]]:
        client = self._get_client()
        query = client.collection(self.collection_name).where("tenant_id", "==", tenant_id)
        docs = [d async for d in query.stream()]
        return [self._doc_to_dict(d.to_dict()) for d in docs]

    async def get_server(self, tenant_id: str, server_id: str) -> dict[str, Any] | None:
        client = self._get_client()
        doc_id = f"{tenant_id}_{server_id}"
        doc_ref = client.collection(self.collection_name).document(doc_id)
        doc = await doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            if data.get("tenant_id") == tenant_id:
                return self._doc_to_dict(data)
        return None

    async def create_server(self, tenant_id: str, server_data: dict[str, Any]) -> dict[str, Any]:
        client = self._get_client()
        server_id = server_data["id"]
        doc_id = f"{tenant_id}_{server_id}"
        doc_ref = client.collection(self.collection_name).document(doc_id)

        data = dict(server_data)
        data["tenant_id"] = tenant_id
        await doc_ref.set(data)
        return data

    async def update_server(self, tenant_id: str, server_id: str, update_data: dict[str, Any]) -> dict[str, Any] | None:
        client = self._get_client()
        doc_id = f"{tenant_id}_{server_id}"
        doc_ref = client.collection(self.collection_name).document(doc_id)
        doc = await doc_ref.get()
        if not doc.exists:
            return None
        await doc_ref.update(update_data)
        return await self.get_server(tenant_id, server_id)

    async def delete_server(self, tenant_id: str, server_id: str) -> bool:
        client = self._get_client()
        doc_id = f"{tenant_id}_{server_id}"
        doc_ref = client.collection(self.collection_name).document(doc_id)
        await doc_ref.delete()
        return True
