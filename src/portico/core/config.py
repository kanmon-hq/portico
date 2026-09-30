"""
MCP Gateway — 設定管理モジュール
"""

from __future__ import annotations

import os

ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()
ALLOW_LOCAL_MCP_SERVERS = os.getenv(
    "ALLOW_LOCAL_MCP_SERVERS",
    "true" if ENVIRONMENT != "production" else "false",
).lower() in ("true", "1", "yes")
MOCK_EXTERNAL_APIS = os.getenv(
    "MOCK_EXTERNAL_APIS",
    "true" if ENVIRONMENT != "production" else "false",
).lower() in ("true", "1", "yes")

ROOT_PATH = os.getenv("ROOT_PATH", "/gateway")
OPENAPI_PATH = os.getenv("OPENAPI_PATH", "/openapi.json")
DOCS_PATH = os.getenv("DOCS_PATH")
REDOC_URL = os.getenv("REDOC_URL")
SCALAR_URL = os.getenv("SCALAR_URL", os.getenv("SCALAR_DOCS_URL"))
MAX_SERVERS_PER_TENANT = int(os.getenv("MAX_SERVERS_PER_TENANT", "50"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")


# ── Gateway 共有シークレット認証設定 (Kura 準拠) ─────────────────────────
# 認証ゲートウェイ (Tollgate / Proxy 等) からのアクセスを相互信頼確認する共有シークレット
GATEWAY_SHARED_SECRET = os.getenv("GATEWAY_SHARED_SECRET")
GATEWAY_SHARED_SECRET_PREVIOUS = os.getenv("GATEWAY_SHARED_SECRET_PREVIOUS")
GATEWAY_SECRET_HEADER = os.getenv("GATEWAY_SECRET_HEADER", "X-Gateway-Secret")
INSECURE_NO_GATEWAY_AUTH = os.getenv("INSECURE_NO_GATEWAY_AUTH", "false").lower() in ("true", "1", "yes")
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "tenant_default")

# ── ストレージ設定 (Zero-Ops / Multi-Cloud) ─────────────────────────────
# sqlite (既定) | dynamodb (AWS) | firestore (GCP) | cosmosdb (Azure)
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "sqlite").lower()

# SQLite 設定
SQLITE_PATH = os.getenv("SQLITE_PATH", "portico.db")

# AWS DynamoDB 設定
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "portico_servers")
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-northeast-1"))
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT", os.getenv("AWS_ENDPOINT_URL"))

# GCP Firestore 設定
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", "portico_servers")
FIRESTORE_PROJECT_ID = os.getenv("FIRESTORE_PROJECT_ID")

# Azure Cosmos DB 設定
COSMOSDB_ENDPOINT = os.getenv("COSMOSDB_ENDPOINT")
COSMOSDB_KEY = os.getenv("COSMOSDB_KEY")
COSMOSDB_DATABASE = os.getenv("COSMOSDB_DATABASE", "portico_db")
COSMOSDB_CONTAINER = os.getenv("COSMOSDB_CONTAINER", "portico_servers")

# ── 二段キャッシュ設定 (L1: In-Memory, L2: Valkey/Redis) ──────────────────
# two_tier (既定: L1+L2) | memory (L1のみ) | valkey (L2のみ) | none (キャッシュ無効)
CACHE_LAYER = os.getenv("CACHE_LAYER", "two_tier" if os.getenv("VALKEY_URL") or os.getenv("REDIS_URL") else "memory").lower()
CACHE_L1_TTL_SECONDS = int(os.getenv("CACHE_L1_TTL_SECONDS", "30"))
CACHE_L1_MAXSIZE = int(os.getenv("CACHE_L1_MAXSIZE", "1000"))
CACHE_L2_TTL_SECONDS = int(os.getenv("CACHE_L2_TTL_SECONDS", "300"))
VALKEY_URL = os.getenv("VALKEY_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 外部 MCP サーバー連携・ツールキャッシュ設定
TOOL_CACHE_TTL_SECONDS = int(os.getenv("TOOL_CACHE_TTL_SECONDS", "60"))
EXTERNAL_MCP_TIMEOUT_SECONDS = float(os.getenv("EXTERNAL_MCP_TIMEOUT_SECONDS", "5.0"))


def get_valid_gateway_secrets() -> list[str]:
    """現在有効な Gateway 共有シークレット一覧（新旧ローテーション対応）を返す。"""
    secrets_list: list[str] = []
    if GATEWAY_SHARED_SECRET and GATEWAY_SHARED_SECRET.strip():
        secrets_list.append(GATEWAY_SHARED_SECRET.strip())
    if GATEWAY_SHARED_SECRET_PREVIOUS and GATEWAY_SHARED_SECRET_PREVIOUS.strip():
        secrets_list.append(GATEWAY_SHARED_SECRET_PREVIOUS.strip())
    return secrets_list


def validate_gateway_auth_config() -> None:
    """
    起動時に Gateway 共有シークレット設定を検証する (Fail-Fast)。
    INSECURE_NO_GATEWAY_AUTH=false かつシークレット未設定の場合は起動を拒否する。
    """
    if INSECURE_NO_GATEWAY_AUTH:
        return

    valid_secrets = get_valid_gateway_secrets()
    if not valid_secrets:
        if ENVIRONMENT == "production":
            raise RuntimeError("GATEWAY_SHARED_SECRET must be set in production (or enable INSECURE_NO_GATEWAY_AUTH=true for local dev)")
    else:
        for s in valid_secrets:
            if len(s) < 32 and ENVIRONMENT == "production":
                raise RuntimeError("GATEWAY_SHARED_SECRET must be at least 32 characters long in production")
