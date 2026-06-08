"""
异步 PostgreSQL 连接 — 使用 asyncpg
遵循项目原始 SQL 模式（无 ORM）

S5-16: 新增事务支持
S5-17: 连接池参数从 config 读取
"""
import asyncpg
from contextlib import asynccontextmanager
from typing import Optional, AsyncIterator

from config import settings


class Database:
    _pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def connect(cls) -> None:
        cls._pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=getattr(settings, "DB_POOL_MIN_SIZE", 2),
            max_size=getattr(settings, "DB_POOL_MAX_SIZE", 10),
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

    # S5-16: 事务支持
    @classmethod
    @asynccontextmanager
    async def transaction(cls) -> AsyncIterator[asyncpg.Connection]:
        """获取一个带事务的连接，自动 commit/rollback"""
        async with cls._pool.acquire() as conn:
            async with conn.transaction():
                yield conn

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
