"""
Memory Consolidation — 异步记忆巩固
严格对应 Step 8 文档 8.2

触发时机: Reflection Agent 完成后异步触发
窗口: 7 天内出现 ≥ 3 次的相同语义事实 → 从 Episodic 提升至 Semantic
写入: 通过 fe_ingest Tool，importance = 0.8
去重: 相同 namespace + 相似度 > 0.95 的 Semantic 条目合并（FE 侧负责）
"""
import asyncio
import json
import logging
from collections import Counter
from typing import Any

from app.tools.fe_client import fe_retrieve, fe_ingest
from app.tools.models import FERetrieveInput, FEIngestInput
from app.tools.embedding import cosine_similarity, embed_single
from db_util import db

logger = logging.getLogger(__name__)

# ============================================================
# 配置常量
# ============================================================

CONSOLIDATION_WINDOW_DAYS = 7        # 回顾窗口: 7 天
CONSOLIDATION_MIN_FREQ = 3           # 最小出现次数: ≥ 3 次
CONSOLIDATION_IMPORTANCE = 0.8       # Semantic 记忆重要度
CONSOLIDATION_SIMILARITY_THRESHOLD = 0.95  # 相似度阈值（FE 侧负责去重）


# ============================================================
# Memory Consolidation
# ============================================================


class MemoryConsolidation:
    """
    Memory Consolidation — 将 Episodic 记忆提升至 Semantic 记忆。

    算法:
    1. 查询 agent_audit_log 中最近 7 天的 Reflection 结果
    2. 提取所有 lesson / rule_candidate
    3. 聚类统计：相同语义 fact 出现 ≥ 3 次 → 标记为 candidate
    4. 对每个 candidate 执行 embedding 去重检查（与现有 Semantic 记忆比对）
    5. 通过 fe_ingest 写入 Semantic 层
    """

    name: str = "memory_consolidation"

    async def find_episodic_patterns(
        self, user_id: int, tenant_id: int
    ) -> list[dict[str, Any]]:
        """
        从 agent_audit_log 中提取 7 天内的 Reflection 结果。
        """
        rows = await db.fetch(
            """
            SELECT event_data
            FROM agent_audit_log
            WHERE agent_name = 'reflection'
              AND event_type = 'reflection_complete'
              AND created_at >= NOW() - INTERVAL '7 days'
              AND event_data IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 100
            """
        )

        lessons: list[str] = []
        for row in rows:
            try:
                data = json.loads(row["event_data"]) if isinstance(row["event_data"], str) else row["event_data"]
                lesson = data.get("lesson", "").strip()
                rule = data.get("rule_candidate", "").strip()
                if lesson and lesson not in ("", "null", "None"):
                    lessons.append(lesson)
                if rule and rule not in ("", "null", "None"):
                    lessons.append(rule)
            except (json.JSONDecodeError, TypeError):
                continue

        # 统计频率
        freq: Counter = Counter(lessons)

        # 筛选 ≥ 3 次的 pattern
        candidates = []
        for text, count in freq.items():
            if count >= CONSOLIDATION_MIN_FREQ:
                candidates.append({
                    "text": text,
                    "frequency": count,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                })

        logger.info(
            f"[MemoryConsolidation] user={user_id} found {len(lessons)} lessons, "
            f"{len(candidates)} candidates (freq >= {CONSOLIDATION_MIN_FREQ})"
        )
        return candidates

    async def check_semantic_similarity(
        self, text: str, namespace: str
    ) -> bool:
        """
        检查候选 fact 是否与现有 Semantic 记忆高度相似。
        返回 True 表示应该合并（相似度 > 0.95），False 表示新记忆。

        去重策略: embedding 向量余弦相似度 > 0.95 → 合并
        """
        try:
            # 获取候选 text 的 embedding
            cand_embedding = await embed_single(text)

            # 查询现有 Semantic 记忆
            retrieve_input = FERetrieveInput(
                query=text,
                layer="semantic",
                n=5,
                user_id=0,  # namespace 级别查询
                namespace=namespace,
            )
            from app.tools.fe_client import fe_retrieve
            result = await fe_retrieve(retrieve_input)

            if result.retrieved_count == 0:
                return False  # 无相似记忆，是新记忆

            # 检查相似度
            for item in result.raw_items:
                try:
                    item_embedding = await embed_single(item.text)
                    similarity = cosine_similarity(cand_embedding, item_embedding)
                    if similarity > CONSOLIDATION_SIMILARITY_THRESHOLD:
                        logger.debug(
                            f"[MemoryConsolidation] similar semantic memory found: "
                            f"similarity={similarity:.4f} text={item.text[:80]}"
                        )
                        return True
                except Exception:
                    continue

            return False

        except Exception as e:
            logger.warning(f"[MemoryConsolidation] similarity check failed: {e}")
            return False  # 失败时保守处理，当作新记忆

    async def consolidate(
        self, user_id: int, tenant_id: int
    ) -> dict[str, Any]:
        """
        执行一次 Memory Consolidation 循环。

        Returns:
            {"consolidated": int, "merged": int, "errors": int}
        """
        result = {"consolidated": 0, "merged": 0, "errors": 0}

        # Step 1: 查找候选 pattern
        candidates = await self.find_episodic_patterns(user_id, tenant_id)
        if not candidates:
            logger.info(f"[MemoryConsolidation] user={user_id} no candidates")
            return result

        namespace = f"tenant:{tenant_id}:agent:reflection"

        # Step 2: 逐个检查并写入
        for candidate in candidates:
            text = candidate["text"]
            freq = candidate["frequency"]

            try:
                # 检查是否已存在相似 Semantic 记忆
                is_duplicate = await self.check_semantic_similarity(text, namespace)
                if is_duplicate:
                    result["merged"] += 1
                    logger.debug(
                        f"[MemoryConsolidation] merged: text={text[:100]} freq={freq}"
                    )
                    continue

                # 通过 fe_ingest 写入 Semantic 层
                ingest_input = FEIngestInput(
                    text=text,
                    role="assistant",
                    session_id=f"consolidation:{user_id}",
                    user_id=user_id,
                    namespace=namespace,
                    importance=CONSOLIDATION_IMPORTANCE,
                )
                ingest_result = await fe_ingest(ingest_input)

                if ingest_result.success:
                    result["consolidated"] += 1
                    logger.info(
                        f"[MemoryConsolidation] consolidated: text={text[:100]} "
                        f"freq={freq} ns={namespace}"
                    )

                    # 记录到 audit_log
                    await db.execute(
                        """
                        INSERT INTO agent_audit_log (session_id, agent_name, event_type, event_data)
                        VALUES ($1, $2, $3, $4)
                        """,
                        f"consolidation:{user_id}",
                        "memory_consolidation",
                        "memory_promoted",
                        json.dumps({
                            "text": text[:500],
                            "frequency": freq,
                            "layer": "semantic",
                            "importance": CONSOLIDATION_IMPORTANCE,
                            "namespace": namespace,
                        }, ensure_ascii=False),
                    )
                else:
                    result["errors"] += 1
                    logger.warning(
                        f"[MemoryConsolidation] fe_ingest failed for text={text[:100]}"
                    )

            except Exception as e:
                result["errors"] += 1
                logger.error(f"[MemoryConsolidation] error consolidating text={text[:100]}: {e}")

        logger.info(
            f"[MemoryConsolidation] user={user_id} done: "
            f"consolidated={result['consolidated']} "
            f"merged={result['merged']} "
            f"errors={result['errors']}"
        )

        return result


# ============================================================
# 异步触发入口
# ============================================================


async def trigger_memory_consolidation_async(
    user_id: int, tenant_id: int,
) -> dict[str, Any]:
    """
    异步触发 Memory Consolidation（不阻塞主流程）。

    用法:
        asyncio.create_task(trigger_memory_consolidation_async(user_id, tenant_id))
    """
    consolidator = MemoryConsolidation()

    try:
        result = await consolidator.consolidate(user_id, tenant_id)
        return result
    except Exception as e:
        logger.error(f"[MemoryConsolidation] failed for user={user_id}: {e}")
        return {"consolidated": 0, "merged": 0, "errors": 1}


# 全局单例
memory_consolidation = MemoryConsolidation()
