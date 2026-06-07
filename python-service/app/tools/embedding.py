"""
Embedding 服务 + Redis 缓存 — 严格对应 Step 5 文档 5.9
- 模型: text-embedding-v4, 维度 1024
- 缓存 Key: embed_cache:{sha256(text)}, TTL 3600s
- 缓存命中 → 直接返回向量，跳过 API 调用
"""
import hashlib
import asyncio
from typing import Optional

import numpy as np
from openai import AsyncOpenAI

from config import settings
from redis_util import redis_client

_embedding_client: Optional[AsyncOpenAI] = None
_embedding_lock = asyncio.Lock()


def _get_client() -> AsyncOpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )
    return _embedding_client


def _cache_key(text: str) -> str:
    """embed_cache:{sha256(text)}"""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"embed_cache:{h}"


async def embed_single(text: str) -> list[float]:
    """
    对单条文本生成 embedding 向量，优先走 Redis 缓存
    返回: 1024 维浮点列表
    """
    # 1. 检查 Redis 缓存
    key = _cache_key(text)
    try:
        cached = await redis_client.get(key)
        if cached is not None:
            # 缓存格式: "0.123,0.456,..." (逗号分隔)
            return [float(x) for x in cached.split(",")]
    except Exception:
        pass  # Redis 不可用时降级为直接 API 调用

    # 2. 调用 embedding API
    client = _get_client()
    resp = await client.embeddings.create(
        input=text,
        model=settings.EMBEDDING_MODEL,
    )
    vec = resp.data[0].embedding

    # 3. 写入 Redis 缓存（异步，不阻塞返回）
    try:
        cache_val = ",".join(str(v) for v in vec)
        await redis_client.set(key, cache_val, ttl=settings.EMBEDDING_CACHE_TTL)
    except Exception:
        pass

    return vec


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    批量生成 embedding 向量，优先走 Redis 缓存
    返回: 多个 1024 维浮点列表
    """
    if not texts:
        return []

    results = [None] * len(texts)
    uncached_indices = []

    # 1. 批量检查 Redis 缓存
    for i, t in enumerate(texts):
        key = _cache_key(t)
        try:
            cached = await redis_client.get(key)
            if cached is not None:
                results[i] = [float(x) for x in cached.split(",")]
                continue
        except Exception:
            pass
        uncached_indices.append(i)

    if not uncached_indices:
        return results

    # 2. 对未缓存的文本调用 API
    client = _get_client()
    api_resp = await client.embeddings.create(
        input=[texts[i] for i in uncached_indices],
        model=settings.EMBEDDING_MODEL,
    )

    # 3. 填充结果 + 写缓存
    for j, emb_data in enumerate(api_resp.data):
        idx = uncached_indices[j]
        vec = emb_data.embedding
        results[idx] = vec

        try:
            cache_key = _cache_key(texts[idx])
            cache_val = ",".join(str(v) for v in vec)
            await redis_client.set(cache_key, cache_val, ttl=settings.EMBEDDING_CACHE_TTL)
        except Exception:
            pass

    return results


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度"""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    na = np.linalg.norm(a_arr)
    nb = np.linalg.norm(b_arr)
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))
