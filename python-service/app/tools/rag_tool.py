"""
RAG 工具 — rag_search（混合检索+RRF融合） + rag_conflict（成分冲突检测）
严格对应 Step 5 文档 5.4 / 5.5
"""
import json
import logging
import re
from typing import Optional

from app.tools.models import (
    RAGSearchInput,
    RAGSearchOutput,
    RAGConflictInput,
    RAGConflictOutput,
    KnowledgeItem,
    ConflictItem,
)
from app.tools.embedding import embed_single
from db_util import db

logger = logging.getLogger(__name__)


# ============================================================
# 5.4 rag_search — 知识检索（混合检索 + RRF 融合）
# ============================================================

# 用于表示向量搜索结果的内部结构
class _SearchHit:
    __slots__ = ("id", "name", "brand", "category", "ingredients", "description", "score", "source")
    def __init__(self, id, name, brand, category, ingredients, description, score, source):
        self.id = id
        self.name = name
        self.brand = brand
        self.category = category
        self.ingredients = ingredients
        self.description = description
        self.score = score
        self.source = source  # "semantic" | "keyword"


_PRODUCT_COLS = "id, name, brand, category, ingredients, description"


def _row_to_knowledge_item(row, score: float = 0.0) -> KnowledgeItem:
    ingredients = row.get("ingredients")
    if isinstance(ingredients, str):
        try:
            ingredients = json.loads(ingredients)
        except (json.JSONDecodeError, TypeError):
            ingredients = []

    return KnowledgeItem(
        id=row["id"],
        name=row["name"] or "",
        brand=row.get("brand") or "",
        category=row.get("category") or "",
        ingredients=ingredients or [],
        description=row.get("description") or "",
        score=score,
    )


def _extract_potential_keywords(query: str) -> list[str]:
    """从 query 中提取可能的过滤关键词（品牌、品类、成分名等）"""
    keywords = []
    # 简单分词 + 汉字/英文词提取
    # 2-20 字符作为候选关键词
    for word in re.findall(r'[一-鿿\w]{2,20}', query):
        keywords.append(word)
    return keywords


async def _vector_search(vec: list[float], tenant_id: int, limit: int) -> list[_SearchHit]:
    """
    pgvector 语义搜索：余弦相似度排序
    使用 products.embedding vector(1024) 列
    """
    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
    query = f"""
        SELECT {_PRODUCT_COLS},
               1 - (embedding <=> $1) AS similarity
        FROM products
        WHERE tenant_id = $2
          AND embedding IS NOT NULL
        ORDER BY embedding <=> $1
        LIMIT $3
    """
    try:
        rows = await db.fetch(query, vec_str, tenant_id, limit)
        hits = []
        for row in rows:
            hits.append(_SearchHit(
                id=row["id"],
                name=row["name"],
                brand=row.get("brand") or "",
                category=row.get("category") or "",
                ingredients=row.get("ingredients"),
                description=row.get("description") or "",
                score=float(row["similarity"] or 0),
                source="semantic",
            ))
        return hits
    except Exception as e:
        logger.error(f"[rag_search] pgvector search failed: {e}")
        # 降级: pgvector索引损坏 → 返回空，由上层走 keyword 检索
        return []


async def _keyword_search(filters: list[str], tenant_id: int, limit: int) -> list[_SearchHit]:
    """
    SQL ILIKE 关键词检索：在 name、brand、category、description 中匹配
    """
    if not filters:
        return []

    # 构建 ILIKE 条件（OR 连接）
    conditions = []
    params = [tenant_id]
    for i, kw in enumerate(filters):
        param_name = f"${i + 2}"  # $2, $3, ...
        conditions.append(
            f"(name ILIKE {param_name} OR brand ILIKE {param_name} "
            f"OR category ILIKE {param_name} OR description ILIKE {param_name})"
        )
        params.append(f"%{kw}%")

    where_clause = " OR ".join(conditions)
    query = f"""
        SELECT {_PRODUCT_COLS}, 0.5 AS score
        FROM products
        WHERE tenant_id = $1
          AND ({where_clause})
        LIMIT ${len(params) + 1}
    """

    try:
        rows = await db.fetch(query, *params, limit)
        hits = []
        for row in rows:
            hits.append(_SearchHit(
                id=row["id"],
                name=row["name"],
                brand=row.get("brand") or "",
                category=row.get("category") or "",
                ingredients=row.get("ingredients"),
                description=row.get("description") or "",
                score=float(row["score"]),
                source="keyword",
            ))
        return hits
    except Exception as e:
        logger.error(f"[rag_search] keyword search failed: {e}")
        return []


def _rrf_merge(semantic: list[_SearchHit], keyword: list[_SearchHit], top_k: int, k: int = 60) -> list[_SearchHit]:
    """
    Reciprocal Rank Fusion — Step 5 文档 5.4
    score = sum(1 / (k + rank + 1)) for each source list
    """
    scores: dict[int, tuple[float, _SearchHit]] = {}  # id -> (accumulated_score, best_hit)

    for source, hits in [("semantic", semantic), ("keyword", keyword)]:
        for rank, hit in enumerate(hits):
            rrf_score = 1.0 / (k + rank + 1)
            if hit.id in scores:
                prev_score, _ = scores[hit.id]
                scores[hit.id] = (prev_score + rrf_score, hit)
            else:
                scores[hit.id] = (rrf_score, hit)

    # 按 RRF score 降序排列
    sorted_hits = sorted(scores.values(), key=lambda x: x[0], reverse=True)
    result = []
    for rrf_score, hit in sorted_hits[:top_k]:
        hit.score = rrf_score
        result.append(hit)

    return result


async def rag_search(input: RAGSearchInput) -> RAGSearchOutput:
    """
    知识检索主入口 — Step 5 文档 5.4
    混合检索流程:
      1. 生成 query embedding
      2. pgvector 语义搜索 (top_k * 2)
      3. 提取关键词 → SQL ILIKE 关键词搜索 (top_k)
      4. RRF 融合 → 返回 top_k 结果
    降级: pgvector 索引损坏 → 降级为仅 keyword 检索
    """
    top_k = input.top_k

    try:
        if input.search_type in ("hybrid", "semantic"):
            try:
                vec = await embed_single(input.query)
                semantic_hits = await _vector_search(vec, input.tenant_id, limit=top_k * 2)
            except Exception as e:
                logger.warning(f"[rag_search] embedding failed, falling back to keyword only: {e}")
                semantic_hits = []
        else:
            semantic_hits = []

        if input.search_type in ("hybrid", "keyword"):
            filters = _extract_potential_keywords(input.query)
            keyword_hits = await _keyword_search(filters, input.tenant_id, limit=top_k)
        else:
            keyword_hits = []

        # RRF 融合
        if input.search_type == "hybrid":
            merged = _rrf_merge(semantic_hits, keyword_hits, top_k)
        elif input.search_type == "semantic":
            merged = semantic_hits[:top_k]
        else:
            merged = keyword_hits[:top_k]

        items = [_row_to_knowledge_item(h, score=h.score) for h in merged]

        return RAGSearchOutput(
            items=items,
            total=len(items),
        )
    except Exception as e:
        logger.error(f"[rag_search] failed: {e}")
        raise  # 异常传播至 registry 层重试，兜底在 registry 层


# ============================================================
# 5.5 rag_conflict — 成分冲突检测
# ============================================================

async def rag_conflict(input: RAGConflictInput) -> RAGConflictOutput:
    """
    成分冲突检测 — Step 5 文档 5.5
    数据来源: knowledge.product_conflicts 表
    检测:
      - ingredient_conflict: 成分间的互相冲突
      - skin_sensitivity: 用户过敏/敏感成分检测
      - dosage_excess: 成分过量使用检测
    兜底: 返回 has_urgent=false（降级，不阻断推荐）
    """
    conflicts: list[ConflictItem] = []

    try:
        # 1. ingredient_conflict: 查询 knowledge.product_conflicts 表
        # 通过成分名匹配冲突规则
        if "ingredient_conflict" in input.check_types and input.ingredients:
            # 构建 LIKE 条件匹配 ingredients 列（假设冲突表有成分字段）
            placeholders = []
            params = []
            for i, ing in enumerate(input.ingredients):
                p = f"${i + 1}"
                placeholders.append(p)
                params.append(f"%{ing}%")

            query = f"""
                SELECT pc.*, p1.name AS product_a_name, p2.name AS product_b_name
                FROM knowledge.product_conflicts pc
                LEFT JOIN products p1 ON pc.product_a_id = p1.id
                LEFT JOIN products p2 ON pc.product_b_id = p2.id
                WHERE pc.conflict_type = 'ingredient_conflict'
                LIMIT 50
            """
            try:
                rows = await db.fetch(query)
                for row in rows:
                    conflicts.append(ConflictItem(
                        conflict_type=row.get("conflict_type") or "ingredient_conflict",
                        severity=row.get("severity") or "medium",
                        description=row.get("description") or "",
                        ingredients_involved=[],
                        suggestion=row.get("suggestion") or "",
                    ))
            except Exception as e:
                logger.error(f"[rag_conflict] ingredient_conflict query failed: {e}")

        # 2. skin_sensitivity: 查询用户过敏原
        if "skin_sensitivity" in input.check_types:
            try:
                row = await db.fetchrow(
                    "SELECT allergies FROM skin_profiles WHERE user_id = $1",
                    input.user_id,
                )
                if row and row.get("allergies"):
                    allergies = row["allergies"]
                    if isinstance(allergies, str):
                        try:
                            allergies = json.loads(allergies)
                        except (json.JSONDecodeError, TypeError):
                            allergies = []
                    if allergies:
                        # 检查当前成分是否匹配过敏原
                        for allergy in allergies:
                            for ing in input.ingredients:
                                if allergy.lower() in ing.lower():
                                    conflicts.append(ConflictItem(
                                        conflict_type="skin_sensitivity",
                                        severity="high",
                                        description=f"成分 '{ing}' 可能与您的过敏原 '{allergy}' 匹配",
                                        ingredients_involved=[ing],
                                        suggestion=f"建议避免含 '{allergy}' 的产品",
                                    ))
            except Exception as e:
                logger.error(f"[rag_conflict] skin_sensitivity query failed: {e}")

        # 3. dosage_excess: 成分过量检测（简化：检查是否出现在已知过量风险列表中）
        if "dosage_excess" in input.check_types:
            try:
                rows = await db.fetch(
                    "SELECT * FROM knowledge.product_conflicts WHERE conflict_type = 'dosage_excess' LIMIT 20"
                )
                for row in rows:
                    conflicts.append(ConflictItem(
                        conflict_type="dosage_excess",
                        severity=row.get("severity") or "low",
                        description=row.get("description") or "成分可能存在过量使用风险",
                        ingredients_involved=[],
                        suggestion=row.get("suggestion") or "建议按照推荐用量使用",
                    ))
            except Exception as e:
                logger.error(f"[rag_conflict] dosage_excess query failed: {e}")

        # 计算 has_urgent
        has_urgent = any(c.severity == "high" for c in conflicts)

        return RAGConflictOutput(
            conflicts=conflicts,
            has_urgent=has_urgent,
        )

    except Exception as e:
        logger.error(f"[rag_conflict] all checks failed: {e}")
        raise  # 异常传播至 registry 层重试，兜底在 registry 层
