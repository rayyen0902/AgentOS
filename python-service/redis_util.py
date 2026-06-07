"""
Redis 工具类 — 统一前缀 + TTL + 降级策略
"""

import json
import hashlib
from typing import Any, Optional

import redis.asyncio as aioredis

from config import settings

KEY_PREFIX = "agentos:"


class RedisClient:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._pool: Optional[aioredis.ConnectionPool] = None
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        self._pool = aioredis.ConnectionPool.from_url(
            self.redis_url,
            max_connections=20,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        self._client = aioredis.Redis(connection_pool=self._pool)
        await self._client.ping()

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
        if self._pool:
            await self._pool.disconnect()

    def _build_key(self, key: str) -> str:
        return f"{KEY_PREFIX}{key}"

    async def is_available(self) -> bool:
        try:
            if self._client is None:
                return False
            await self._client.ping()
            return True
        except Exception:
            return False

    async def get(self, key: str) -> Optional[str]:
        result = await self._client.get(self._build_key(key))
        if result is not None:
            return result.decode("utf-8")
        return None

    async def set(self, key: str, value: str, ttl: int = 1800) -> None:
        await self._client.set(self._build_key(key), value, ex=ttl)

    async def set_json(self, key: str, value: Any, ttl: int = 1800) -> None:
        await self._client.set(self._build_key(key), json.dumps(value, ensure_ascii=False), ex=ttl)

    async def get_json(self, key: str) -> Optional[Any]:
        data = await self._client.get(self._build_key(key))
        if data is not None:
            return json.loads(data)
        return None

    async def delete(self, key: str) -> None:
        await self._client.delete(self._build_key(key))

    async def exists(self, key: str) -> bool:
        return await self._client.exists(self._build_key(key)) > 0

    async def expire(self, key: str, ttl: int) -> None:
        await self._client.expire(self._build_key(key), ttl)


redis_client = RedisClient(settings.REDIS_URL)
