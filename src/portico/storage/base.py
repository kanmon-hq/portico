"""
ストレージリポジトリ 基底インターフェース
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseServerRepository(ABC):
    """MCP カスタムサーバー定義の永続化インターフェース"""

    @abstractmethod
    async def init_storage(self) -> None:
        """ストレージの初期化（テーブル・コレクション自動作成等）"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """接続リソースのクローズ"""
        ...

    @abstractmethod
    async def list_servers(self, tenant_id: str) -> list[dict[str, Any]]:
        """指定テナントの登録済みカスタムサーバー一覧を取得"""
        ...

    @abstractmethod
    async def get_server(self, tenant_id: str, server_id: str) -> dict[str, Any] | None:
        """指定テナントの特定サーバー定義を取得"""
        ...

    @abstractmethod
    async def create_server(self, tenant_id: str, server_data: dict[str, Any]) -> dict[str, Any]:
        """新規サーバー定義を保存"""
        ...

    @abstractmethod
    async def update_server(self, tenant_id: str, server_id: str, update_data: dict[str, Any]) -> dict[str, Any] | None:
        """既存サーバー定義を更新"""
        ...

    @abstractmethod
    async def delete_server(self, tenant_id: str, server_id: str) -> bool:
        """サーバー定義を削除"""
        ...
