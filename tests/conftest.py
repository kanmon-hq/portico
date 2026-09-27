"""
Pytest configuration and shared fixtures for portico tests.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path

# Ensure portico/src is in sys.path
_src_dir = str(Path(__file__).resolve().parent.parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from portico.cache.memory_cache import MemoryCache
from portico.main import app
from portico.storage.sqlite import SQLiteServerRepository


@pytest.fixture(autouse=True)
def reset_storage_and_cache(monkeypatch):
    """各テスト実行前にストレージとキャッシュをクリーンな状態にリセットする。"""
    monkeypatch.setattr("portico.core.config.STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr("portico.core.config.CACHE_LAYER", "memory")
    repo = SQLiteServerRepository(db_path=":memory:")
    cache = MemoryCache()
    monkeypatch.setattr("portico.storage.factory._storage_instance", repo)
    monkeypatch.setattr("portico.cache.factory._cache_instance", cache)
    yield
    cache._cache.clear()


@pytest.fixture(autouse=True)
def default_insecure_auth_for_tests(monkeypatch):
    """テスト実行時は既定で INSECURE_NO_GATEWAY_AUTH=True とし、認証テスト時は個別に False に上書きする。"""
    monkeypatch.setattr("portico.core.config.INSECURE_NO_GATEWAY_AUTH", True)
    monkeypatch.setattr("portico.api.deps.INSECURE_NO_GATEWAY_AUTH", True)


@pytest.fixture
def client() -> TestClient:
    """FastAPI 同期テストクライアント。"""
    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient]:
    """FastAPI 非同期テストクライアント。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
