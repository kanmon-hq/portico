"""
ストレージリポジトリ ファクトリモジュール
"""

from __future__ import annotations

import logging

from portico.core.config import STORAGE_BACKEND
from portico.storage.base import BaseServerRepository
from portico.storage.cosmos import CosmosDBServerRepository
from portico.storage.dynamodb import DynamoDBServerRepository
from portico.storage.firestore import FirestoreServerRepository
from portico.storage.sqlite import SQLiteServerRepository

logger = logging.getLogger(__name__)

_storage_instance: BaseServerRepository | None = None


def get_server_repository() -> BaseServerRepository:
    """設定された STORAGE_BACKEND に基づきシングルトンリポジトリを返す"""
    global _storage_instance
    if _storage_instance is None:
        backend = STORAGE_BACKEND.lower()
        if backend == "sqlite":
            _storage_instance = SQLiteServerRepository()
        elif backend == "dynamodb":
            _storage_instance = DynamoDBServerRepository()
        elif backend == "firestore":
            _storage_instance = FirestoreServerRepository()
        elif backend == "cosmosdb":
            _storage_instance = CosmosDBServerRepository()
        else:
            logger.warning("Unknown STORAGE_BACKEND '%s', fallback to SQLite", backend)
            _storage_instance = SQLiteServerRepository()
    return _storage_instance


async def init_storage() -> None:
    """アプリケーション起動時のストレージ初期化"""
    repo = get_server_repository()
    await repo.init_storage()


async def close_storage() -> None:
    """アプリケーション終了時のストレージ破棄"""
    global _storage_instance
    if _storage_instance:
        await _storage_instance.close()
        _storage_instance = None
