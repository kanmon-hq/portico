"""
ストレージリポジトリ (SQLite, DynamoDB, Firestore, Cosmos DB) および
キャッシュ層 (Two-Tier, Memory, Valkey, None) の包括的な単体・モックテスト
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import portico.cache.factory as cache_factory
import portico.storage.factory as storage_factory
from portico.cache.factory import NoOpCache, clear_all_caches, get_cache_service
from portico.cache.memory_cache import MemoryCache
from portico.cache.two_tier_cache import TwoTierCache
from portico.cache.valkey_cache import ValkeyCache
from portico.storage.cosmos import CosmosDBServerRepository
from portico.storage.dynamodb import DynamoDBServerRepository
from portico.storage.factory import close_storage, get_server_repository, init_storage
from portico.storage.firestore import FirestoreServerRepository
from portico.storage.sqlite import SQLiteServerRepository

# ═══════════════════════════════════════════════════════════════════════════════
# 1. ストレージリポジトリ テスト (SQLite, DynamoDB, Firestore, Cosmos DB)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sqlite_repository_crud(tmp_path):
    """SQLite ストレージでの CRUD 操作が正常に行えること"""
    db_file = str(tmp_path / "test_portico.db")
    repo = SQLiteServerRepository(db_path=db_file)
    await repo.init_storage()

    tenant_id = "tenant_test_sql"
    server_data = {
        "id": "srv-1",
        "name": "SQLite Server",
        "url": "https://sqlite.example.com",
        "status": "active",
        "auth_type": "bearer",
        "encrypted_auth_config": "enc-123",
        "scopes": ["read", "write"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    # 1. Create
    created = await repo.create_server(tenant_id, server_data)
    assert created["id"] == "srv-1"
    assert created["tenant_id"] == tenant_id
    assert created["scopes"] == ["read", "write"]

    # 2. Get
    fetched = await repo.get_server(tenant_id, "srv-1")
    assert fetched is not None
    assert fetched["name"] == "SQLite Server"
    assert fetched["auth_type"] == "bearer"

    # 3. List
    servers = await repo.list_servers(tenant_id)
    assert len(servers) == 1
    assert servers[0]["url"] == "https://sqlite.example.com"

    # 4. Update
    updated = await repo.update_server(tenant_id, "srv-1", {"name": "Updated Name", "scopes": ["admin"]})
    assert updated["name"] == "Updated Name"
    assert updated["scopes"] == ["admin"]

    # 5. Delete
    deleted = await repo.delete_server(tenant_id, "srv-1")
    assert deleted is True
    assert await repo.get_server(tenant_id, "srv-1") is None

    await repo.close()


@pytest.mark.asyncio
async def test_dynamodb_repository_crud():
    """DynamoDB ストレージの CRUD およびテーブル初期化のモック検証"""
    repo = DynamoDBServerRepository(table_name="test_servers", region_name="ap-northeast-1")

    # モックテーブルとリソースを設定
    mock_table = MagicMock()
    mock_dynamodb = MagicMock()
    repo._table = mock_table
    repo._dynamodb = mock_dynamodb

    tenant_id = "tenant_dynamo"
    server_data = {
        "id": "srv-dyn-1",
        "name": "Dynamo Server",
        "url": "https://dyn.example.com",
        "status": "active",
        "auth_type": "none",
        "encrypted_auth_config": None,
        "scopes": ["tools:execute"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    # 1. Create
    mock_table.get_item.return_value = {
        "Item": {
            "PK": f"TENANT#{tenant_id}",
            "SK": "SERVER#srv-dyn-1",
            "id": "srv-dyn-1",
            "tenant_id": tenant_id,
            "name": "Dynamo Server",
            "url": "https://dyn.example.com",
            "status": "active",
            "auth_type": "none",
            "encrypted_auth_config": None,
            "scopes": {"tools:execute"},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    }
    created = await repo.create_server(tenant_id, server_data)
    assert created["id"] == "srv-dyn-1"
    mock_table.put_item.assert_called_once()

    # 2. Get
    fetched = await repo.get_server(tenant_id, "srv-dyn-1")
    assert fetched is not None
    assert fetched["name"] == "Dynamo Server"
    assert "tools:execute" in fetched["scopes"]

    # 3. List
    mock_boto3 = MagicMock()
    mock_conditions = MagicMock()
    mock_boto3.dynamodb.conditions = mock_conditions
    mock_conditions.Key = MagicMock()

    with patch.dict("sys.modules", {
        "boto3": mock_boto3,
        "boto3.dynamodb": mock_boto3.dynamodb,
        "boto3.dynamodb.conditions": mock_conditions,
    }):
        mock_table.query.return_value = {"Items": [mock_table.get_item.return_value["Item"]]}
        servers = await repo.list_servers(tenant_id)
        assert len(servers) == 1
        assert servers[0]["id"] == "srv-dyn-1"

    # 4. Update
    updated = await repo.update_server(tenant_id, "srv-dyn-1", {"name": "Updated Dynamo"})
    assert updated is not None

    # 5. Delete
    deleted = await repo.delete_server(tenant_id, "srv-dyn-1")
    assert deleted is True
    mock_table.delete_item.assert_called_once()

    # 6. Init storage (table auto-creation flow)
    mock_table.table_status = "ACTIVE"
    await repo.init_storage()

    await repo.close()
    assert repo._table is None


@pytest.mark.asyncio
async def test_dynamodb_repository_not_found():
    """DynamoDB で対象レコードが存在しない場合の None 返却検証"""
    repo = DynamoDBServerRepository()
    mock_table = MagicMock()
    repo._table = mock_table
    mock_table.get_item.return_value = {}  # Item なし

    assert await repo.get_server("tenant_x", "srv_none") is None
    assert await repo.update_server("tenant_x", "srv_none", {"name": "fail"}) is None


def test_dynamodb_repository_import_error():
    """boto3 がインポートできない場合の適切な例外送出"""
    repo = DynamoDBServerRepository()
    with patch.dict("sys.modules", {"boto3": None}), pytest.raises(RuntimeError, match="boto3 is required"):
        repo._get_resource()


@pytest.mark.asyncio
async def test_firestore_repository_crud():
    """Firestore ストレージの CRUD モック検証"""
    repo = FirestoreServerRepository(collection_name="test_servers", project_id="test-proj")
    mock_client = MagicMock()
    repo._client = mock_client

    tenant_id = "tenant_fs"
    server_data = {
        "id": "srv-fs-1",
        "name": "Firestore Server",
        "url": "https://fs.example.com",
        "status": "active",
        "auth_type": "bearer",
        "encrypted_auth_config": "enc-fs",
        "scopes": ["fs:read"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    mock_doc_ref = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = True
    stored_data = dict(server_data)
    stored_data["tenant_id"] = tenant_id
    mock_doc.to_dict.return_value = stored_data

    # Async methods on doc_ref
    mock_doc_ref.get = AsyncMock(return_value=mock_doc)
    mock_doc_ref.set = AsyncMock()
    mock_doc_ref.update = AsyncMock()
    mock_doc_ref.delete = AsyncMock()

    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_doc_ref

    # query.stream() async iterator mock
    async def _mock_stream():
        yield mock_doc

    mock_query = MagicMock()
    mock_query.stream = _mock_stream
    mock_collection.where.return_value = mock_query

    mock_client.collection.return_value = mock_collection

    # 1. Create
    created = await repo.create_server(tenant_id, server_data)
    assert created["id"] == "srv-fs-1"
    mock_doc_ref.set.assert_awaited_once()

    # 2. Get
    fetched = await repo.get_server(tenant_id, "srv-fs-1")
    assert fetched is not None
    assert fetched["name"] == "Firestore Server"

    # 3. List
    servers = await repo.list_servers(tenant_id)
    assert len(servers) == 1
    assert servers[0]["url"] == "https://fs.example.com"

    # 4. Update
    updated = await repo.update_server(tenant_id, "srv-fs-1", {"name": "Updated FS"})
    assert updated is not None

    # 5. Delete
    deleted = await repo.delete_server(tenant_id, "srv-fs-1")
    assert deleted is True
    mock_doc_ref.delete.assert_awaited_once()

    # 6. Init & Close
    await repo.init_storage()
    await repo.close()
    assert repo._client is None


@pytest.mark.asyncio
async def test_firestore_repository_not_found():
    """Firestore でドキュメントが存在しない場合の None 返却検証"""
    repo = FirestoreServerRepository()
    mock_client = MagicMock()
    repo._client = mock_client

    mock_doc_ref = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_doc_ref.get = AsyncMock(return_value=mock_doc)
    mock_client.collection.return_value.document.return_value = mock_doc_ref

    assert await repo.get_server("tenant_x", "srv_none") is None
    assert await repo.update_server("tenant_x", "srv_none", {"name": "fail"}) is None


def test_firestore_repository_import_error():
    """google-cloud-firestore がインポートできない場合の例外送出"""
    repo = FirestoreServerRepository()
    with patch.dict("sys.modules", {"google.cloud.firestore": None, "google.cloud": None}), pytest.raises(RuntimeError, match="google-cloud-firestore is required"):
        repo._get_client()


@pytest.mark.asyncio
async def test_cosmos_repository_crud():
    """Cosmos DB ストレージの CRUD モック検証"""
    repo = CosmosDBServerRepository(endpoint="https://cosmos.example.com", key="dGVzdA==")
    mock_container = MagicMock()
    repo._container = mock_container

    tenant_id = "tenant_cosmos"
    server_data = {
        "id": "srv-cos-1",
        "name": "Cosmos Server",
        "url": "https://cosmos.example.com",
        "status": "active",
        "auth_type": "none",
        "encrypted_auth_config": None,
        "scopes": ["all"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    cosmos_item = {
        "id": f"{tenant_id}_srv-cos-1",
        "server_id": "srv-cos-1",
        "tenant_id": tenant_id,
        "name": "Cosmos Server",
        "url": "https://cosmos.example.com",
        "status": "active",
        "auth_type": "none",
        "encrypted_auth_config": None,
        "scopes": ["all"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    mock_container.upsert_item = AsyncMock(return_value=cosmos_item)
    mock_container.read_item = AsyncMock(return_value=cosmos_item)
    mock_container.delete_item = AsyncMock()

    # query_items async iterator mock
    async def _mock_query_items(*args, **kwargs):
        yield cosmos_item

    mock_container.query_items = _mock_query_items

    # 1. Create
    created = await repo.create_server(tenant_id, server_data)
    assert created["id"] == "srv-cos-1"
    mock_container.upsert_item.assert_awaited_once()

    # 2. Get
    fetched = await repo.get_server(tenant_id, "srv-cos-1")
    assert fetched is not None
    assert fetched["name"] == "Cosmos Server"

    # 3. List
    servers = await repo.list_servers(tenant_id)
    assert len(servers) == 1
    assert servers[0]["id"] == "srv-cos-1"

    # 4. Update
    updated = await repo.update_server(tenant_id, "srv-cos-1", {"name": "Updated Cosmos"})
    assert updated is not None

    # 5. Delete
    deleted = await repo.delete_server(tenant_id, "srv-cos-1")
    assert deleted is True
    mock_container.delete_item.assert_awaited_once()

    # 6. Init & Close
    await repo.init_storage()
    await repo.close()
    assert repo._container is None


@pytest.mark.asyncio
async def test_cosmos_repository_not_found_and_errors():
    """Cosmos DB でアイテムが存在しない、または削除例外時の安全な処理検証"""
    repo = CosmosDBServerRepository()
    mock_container = MagicMock()
    repo._container = mock_container

    mock_container.read_item = AsyncMock(side_effect=Exception("CosmosResourceNotFoundError"))
    mock_container.delete_item = AsyncMock(side_effect=Exception("CosmosDeleteError"))

    assert await repo.get_server("tenant_x", "srv_none") is None
    assert await repo.update_server("tenant_x", "srv_none", {"name": "fail"}) is None
    assert await repo.delete_server("tenant_x", "srv_none") is False


def test_cosmos_repository_import_error():
    """azure-cosmos がインポートできない場合の例外送出"""
    repo = CosmosDBServerRepository()
    with patch.dict("sys.modules", {"azure.cosmos.aio": None, "azure.cosmos": None}), pytest.raises(RuntimeError, match="azure-cosmos is required"):
        repo._get_container()


@pytest.mark.asyncio
async def test_storage_factory_backends(monkeypatch):
    """STORAGE_BACKEND 設定値に応じたファクトリ生成とフォールバック動作"""
    storage_factory._storage_instance = None

    # 1. sqlite
    monkeypatch.setattr("portico.storage.factory.STORAGE_BACKEND", "sqlite")
    storage_factory._storage_instance = None
    repo_sqlite = get_server_repository()
    assert isinstance(repo_sqlite, SQLiteServerRepository)

    # 2. dynamodb
    monkeypatch.setattr("portico.storage.factory.STORAGE_BACKEND", "dynamodb")
    storage_factory._storage_instance = None
    repo_dynamo = get_server_repository()
    assert isinstance(repo_dynamo, DynamoDBServerRepository)

    # 3. firestore
    monkeypatch.setattr("portico.storage.factory.STORAGE_BACKEND", "firestore")
    storage_factory._storage_instance = None
    repo_fs = get_server_repository()
    assert isinstance(repo_fs, FirestoreServerRepository)

    # 4. cosmosdb
    monkeypatch.setattr("portico.storage.factory.STORAGE_BACKEND", "cosmosdb")
    storage_factory._storage_instance = None
    repo_cos = get_server_repository()
    assert isinstance(repo_cos, CosmosDBServerRepository)

    # 5. unknown -> fallback to SQLite
    monkeypatch.setattr("portico.storage.factory.STORAGE_BACKEND", "invalid_backend")
    storage_factory._storage_instance = None
    repo_fallback = get_server_repository()
    assert isinstance(repo_fallback, SQLiteServerRepository)

    # 6. init_storage & close_storage lifecycle
    with patch.object(repo_fallback, "init_storage", new_callable=AsyncMock) as mock_init, \
         patch.object(repo_fallback, "close", new_callable=AsyncMock) as mock_close:
        await init_storage()
        mock_init.assert_awaited_once()
        await close_storage()
        mock_close.assert_awaited_once()
        assert storage_factory._storage_instance is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. キャッシュ層 テスト (MemoryCache, ValkeyCache, TwoTierCache, NoOpCache)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_memory_cache_l1_behavior():
    """L1 メモリキャッシュの set/get/delete/prefix/clear が機能すること"""
    cache = MemoryCache(maxsize=10, ttl=5)

    await cache.set("key1", {"data": 123})
    assert await cache.get("key1") == {"data": 123}

    await cache.set("tools:t1", [1, 2, 3])
    await cache.set("tools:t2", [4, 5])
    await cache.delete_prefix("tools:")
    assert await cache.get("tools:t1") is None
    assert await cache.get("tools:t2") is None
    assert await cache.get("key1") == {"data": 123}

    await cache.clear()
    assert await cache.get("key1") is None


@pytest.mark.asyncio
async def test_valkey_cache_l2_behavior():
    """L2 分散キャッシュ (Valkey / Redis) のモック検証"""
    cache = ValkeyCache(url="redis://localhost:6379/0", default_ttl=60)
    mock_redis = AsyncMock()
    cache._redis = mock_redis

    # 1. Set & Get
    mock_redis.get.return_value = json.dumps({"status": "cached"})
    await cache.set("user:200", {"status": "cached"}, ttl=30)
    mock_redis.set.assert_awaited_once_with("user:200", json.dumps({"status": "cached"}), ex=30)

    val = await cache.get("user:200")
    assert val == {"status": "cached"}

    # 2. Get Miss
    mock_redis.get.return_value = None
    assert await cache.get("missing_key") is None

    # 3. Delete
    await cache.delete("user:200")
    mock_redis.delete.assert_awaited_with("user:200")

    # 4. Delete Prefix
    async def _mock_scan_iter(match=None):
        yield "prefix:1"
        yield "prefix:2"

    mock_redis.scan_iter = _mock_scan_iter
    await cache.delete_prefix("prefix:")
    mock_redis.delete.assert_awaited_with("prefix:1", "prefix:2")

    # 5. Clear
    await cache.clear()
    mock_redis.flushdb.assert_awaited_once()

    # 6. Error handling robustness
    mock_redis.get.side_effect = Exception("Connection refused")
    assert await cache.get("error_key") is None


@pytest.mark.asyncio
async def test_two_tier_cache_composite_behavior():
    """TwoTierCache で L1 -> L2 のフォールバックと伝播が機能すること"""
    l1 = MemoryCache(maxsize=10, ttl=10)
    l2 = MemoryCache(maxsize=10, ttl=10)  # L2 モックとして MemoryCache を代用
    two_tier = TwoTierCache(l1_cache=l1, l2_cache=l2)

    # 1. Two-Tier Set (両方に書き込まれる)
    await two_tier.set("user:100", {"name": "Alice"})
    assert await l1.get("user:100") == {"name": "Alice"}
    assert await l2.get("user:100") == {"name": "Alice"}

    # 2. L1 のみ破棄した場合、L2 からフェッチされて L1 に再配置される
    await l1.delete("user:100")
    assert await l1.get("user:100") is None

    val = await two_tier.get("user:100")
    assert val == {"name": "Alice"}
    assert await l1.get("user:100") == {"name": "Alice"}  # L1 にキャッシュ補充された

    # 3. Delete Prefix (両方から削除)
    await two_tier.set("tool:alpha", "1")
    await two_tier.set("tool:beta", "2")
    await two_tier.delete_prefix("tool:")
    assert await two_tier.get("tool:alpha") is None
    assert await two_tier.get("tool:beta") is None

    # 4. Two-Tier Delete (両方から削除)
    await two_tier.delete("user:100")
    assert await l1.get("user:100") is None
    assert await l2.get("user:100") is None

    # 5. Clear (両方クリア)
    await two_tier.set("item:1", 1)
    await two_tier.clear()
    assert await two_tier.get("item:1") is None


@pytest.mark.asyncio
async def test_noop_cache_behavior():
    """NoOpCache (CACHE_LAYER=none) はキャッシュをバイパスし副作用を起こさないこと"""
    cache = NoOpCache()
    assert await cache.get("any_key") is None
    await cache.set("any_key", {"data": 123})
    assert await cache.get("any_key") is None
    await cache.delete("any_key")
    await cache.delete_prefix("any_")
    await cache.clear()


@pytest.mark.asyncio
async def test_cache_factory_modes(monkeypatch):
    """CACHE_LAYER 設定値に応じたファクトリ生成と全キャッシュフラッシュ"""
    cache_factory._cache_instance = None

    # 1. two_tier
    monkeypatch.setattr("portico.cache.factory.CACHE_LAYER", "two_tier")
    cache_factory._cache_instance = None
    c_two_tier = get_cache_service()
    assert isinstance(c_two_tier, TwoTierCache)

    # 2. memory
    monkeypatch.setattr("portico.cache.factory.CACHE_LAYER", "memory")
    cache_factory._cache_instance = None
    c_mem = get_cache_service()
    assert isinstance(c_mem, MemoryCache)

    # 3. valkey / redis
    monkeypatch.setattr("portico.cache.factory.CACHE_LAYER", "valkey")
    cache_factory._cache_instance = None
    c_valkey = get_cache_service()
    assert isinstance(c_valkey, ValkeyCache)

    monkeypatch.setattr("portico.cache.factory.CACHE_LAYER", "redis")
    cache_factory._cache_instance = None
    c_redis = get_cache_service()
    assert isinstance(c_redis, ValkeyCache)

    # 4. none
    monkeypatch.setattr("portico.cache.factory.CACHE_LAYER", "none")
    cache_factory._cache_instance = None
    c_none = get_cache_service()
    assert isinstance(c_none, NoOpCache)

    # 5. unknown -> fallback to TwoTierCache
    monkeypatch.setattr("portico.cache.factory.CACHE_LAYER", "invalid_layer")
    cache_factory._cache_instance = None
    c_fallback = get_cache_service()
    assert isinstance(c_fallback, TwoTierCache)

    # 6. clear_all_caches
    with patch.object(c_fallback, "clear", new_callable=AsyncMock) as mock_clear:
        await clear_all_caches()
        mock_clear.assert_awaited_once()
