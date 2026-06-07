"""
Memory Consolidation — Step 5 文档 5.10 规则实现
由 Reflection Agent 异步触发

规则:
  - 触发时机: 每次对话结束后，由 Reflection Agent 异步触发
  - 窗口: 7天内出现 ≥3 次的相同语义事实 → 从 Episodic 提升至 Semantic
  - 写入: 通过 fe_ingest Tool, importance = 0.8
  - 去重: 相同 namespace + 相似度 > 0.95 的 Semantic 条目合并（FE 侧负责）
"""
import logging
import json
from datetime import datetime, timedelta
from typing import Optional

from app.tools.models import MemoryItem, FEIngestInput
from app.tools.registry import fe_ingest_async, fe_retrieve
from app.tools.models import FERetrieveInput, FERetrieveOutput
from app.tools.embedding import cosine_similarity, embed_single
from db_util import db

logger = logging.getLogger(__name__)

# 窗口配置
CONSOLIDATION_WINDOW_DAYS = 7       # 7天内
CONSOLIDATION_MIN_OCCURRENCES = 3    # 出现 ≥3 次
CONSOLIDATION_SIMILARITY_THRESHOLD = 0.95  # 相似度 > 0.95
CONSOLIDATION_IMPORTANCE = 0.8       # 提升至 Semantic 时的 importance


async def run_consolidation(
    user_id: int,
    namespace: str,
    session_id: str,
) -> int:
    """
    Memory Consolidation 主入口 — Step 5 文档 5.10

    流程:
      1. 查询 agent_audit_log 获取7天内的 episodic 记忆事件
      2. 提取高频语义事实 (≥3 次)
      3. 检查是否已存在于 Semantic 层（相似度 > 0.95 则跳过）
      4. 写入 Semantic 层 (importance = 0.8)

    返回: 实际 consolidate 的条目数
    """
    try:
        # 1. 查询7天内的 episodic 类型 audit_log
        since = datetime.utcnow() - timedelta(days=CONSOLIDATION_WINDOW_DAYS)
        rows = await db.fetch(
            """SELECT event_data FROM agent_audit_log
               WHERE created_at >= $1
                 AND event_type = 'memory_write'
               ORDER BY created_at DESC
               LIMIT 500""",
            since,
        )

        if not rows:
            logger.info(f"[consolidation] no recent memory events for namespace={namespace}")
            return 0

        # 2. 提取文本并统计频率
        text_counts: dict[str, int] = {}
        for row in rows:
            event_data = row.get("event_data")
            if isinstance(event_data, str):
                try:
                    event_data = json.loads(event_data)
                except (json.JSONDecodeError, TypeError):
                    continue

            event_ns = (event_data or {}).get("namespace", "")
            if namespace != event_ns:
                continue  # 只 consolidate 同一 namespace

            text = (event_data or {}).get("text", "")
            if not text:
                continue

            text_counts[text] = text_counts.get(text, 0) + 1

        # 筛选 ≥3 次的文本
        candidates = {
            text: count
            for text, count in text_counts.items()
            if count >= CONSOLIDATION_MIN_OCCURRENCES
        }

        if not candidates:
            logger.info(f"[consolidation] no candidates meeting threshold for namespace={namespace}")
            return 0

        # 3. 查询已有 Semantic 记忆，去重
        existing = await fe_retrieve(FERetrieveInput(
            query="*",
            layer="semantic",
            n=50,
            user_id=user_id,
            namespace=namespace,
        ))
        existing_texts = [item.text for item in existing.raw_items]

        # 对 candidate texts 和 existing texts 做 embedding 相似度去重
        consolidated_count = 0
        for text, count in candidates.items():
            # 检查是否与已有 semantic 条目相似
            is_duplicate = False
            if existing_texts:
                try:
                    text_vec = await embed_single(text)
                    for ext in existing_texts:
                        ext_vec = await embed_single(ext)
                        sim = cosine_similarity(text_vec, ext_vec)
                        if sim > CONSOLIDATION_SIMILARITY_THRESHOLD:
                            is_duplicate = True
                            break
                except Exception as e:
                    logger.warning(f"[consolidation] embedding compare failed: {e}")
                    # embedding 失败时保守处理，不做 dedup
                    pass

            if is_duplicate:
                logger.debug(f"[consolidation] skipping duplicate: '{text[:50]}...'")
                continue

            # 4. 写入 Semantic 层
            await fe_ingest_async(FEIngestInput(
                text=f"[Consolidated ×{count}] {text}",
                role="assistant",
                session_id=session_id,
                user_id=user_id,
                namespace=namespace,
                importance=CONSOLIDATION_IMPORTANCE,
            ))
            consolidated_count += 1

        logger.info(
            f"[consolidation] namespace={namespace}: "
            f"{len(candidates)} candidates, {consolidated_count} consolidated "
            f"(skipped {len(candidates) - consolidated_count} duplicates)"
        )

        return consolidated_count

    except Exception as e:
        logger.error(f"[consolidation] failed for namespace={namespace}: {e}")
        return 0
