"""
异步 PostgreSQL 连接 — 使用 asyncpg
遵循项目原始 SQL 模式（无 ORM）
"""
import asyncpg
from typing import Optional

from config import settings


class Database:
    _pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def connect(cls) -> None:
        cls._pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=2,
            max_size=10,
        )

    @classmethod
    async def disconnect(cls) -> None:
        if cls._pool:
            await cls._pool.close()

    @classmethod
    async def fetch(cls, query: str, *args):
        async with cls._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    @classmethod
    async def fetchrow(cls, query: str, *args):
        async with cls._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    @classmethod
    async def execute(cls, query: str, *args) -> str:
        async with cls._pool.acquire() as conn:
            return await conn.execute(query, *args)

    @classmethod
    async def fetchval(cls, query: str, *args):
        async with cls._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    @classmethod
    async def is_available(cls) -> bool:
        try:
            if cls._pool is None:
                return False
            async with cls._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False


db = Database()
