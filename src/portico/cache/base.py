"""
キャッシュ層 基底インターフェース
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCache(ABC):
    """キャッシュサービスの基底インターフェース"""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """キャッシュ値を取得"""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """キャッシュ値を設定"""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """キャッシュキーを削除"""
        ...

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> None:
        """指定プレフィックスに一致するキーを一括削除"""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """全キャッシュをクリア"""
        ...
