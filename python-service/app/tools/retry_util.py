"""
Tool 层重试 + 兜底工具 — 严格对应 Step 5 文档 5.8 重试策略汇总

| Tool | 最大重试 | 重试间隔 | 失败兜底 |
|------|---------|---------|----------|
| fe_retrieve | 2 次 | 500ms | 返回空上下文 |
| fe_ingest | 3 次 | 1s | 记录失败日志，不阻断主流程 |
| rag_search | 2 次 | 500ms | 返回空结果 |
| rag_conflict | 2 次 | 500ms | 返回 has_urgent=false |
| product_crud | 1 次 | 立即 | 返回错误 |
| profile_query | 2 次 | 500ms | 返回空 profile |
"""
import asyncio
import functools
import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# 每个 Tool 的重试配置
RETRY_CONFIG: dict[str, dict[str, Any]] = {
    "fe_retrieve":   {"max_retries": 2, "delay_s": 0.5},
    "fe_ingest":     {"max_retries": 3, "delay_s": 1.0},
    "rag_search":    {"max_retries": 2, "delay_s": 0.5},
    "rag_conflict":  {"max_retries": 2, "delay_s": 0.5},
    "product_crud":  {"max_retries": 1, "delay_s": 0.0},
    "profile_query": {"max_retries": 2, "delay_s": 0.5},
}


async def with_retry(
    tool_name: str,
    fn: Callable[..., Coroutine[Any, Any, Any]],
    *args,
    **kwargs,
):
    """
    按工具名称配置的重试策略执行异步函数。
    重试 N 次后仍失败 → 返回 None（由调用方决定兜底逻辑）
    """
    cfg = RETRY_CONFIG.get(tool_name, {"max_retries": 0, "delay_s": 0.0})
    max_retries = cfg["max_retries"]
    delay_s = cfg["delay_s"]

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(
                    f"[{tool_name}] attempt {attempt + 1}/{max_retries + 1} failed: {e}, "
                    f"retrying in {delay_s}s..."
                )
                await asyncio.sleep(delay_s)
            else:
                logger.error(
                    f"[{tool_name}] all {max_retries + 1} attempts failed: {e}"
                )

    return None  # 重试耗尽，返回 None 由调用方兜底
