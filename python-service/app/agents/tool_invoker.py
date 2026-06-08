"""
Tool 调用层 — 各 Agent 通过此层调用 Step 5 的 6 个 Tool
包含重试、兜底、降级策略，严格对应 Step 6 文档 6.6 系统故障边界
"""
import json
import logging
from typing import Any

from app.tools.models import (
    FERetrieveInput,
    FERetrieveOutput,
    FEIngestInput,
    FEIngestOutput,
    RAGSearchInput,
    RAGSearchOutput,
    RAGConflictInput,
    RAGConflictOutput,
    ProductCRUDInput,
    ProductCRUDOutput,
    ProfileQueryInput,
    ProfileQueryOutput,
    ConflictItem,
    KnowledgeItem,
    MemoryItem,
    ProductItem,
)
from app.tools.retry_util import with_retry
from redis_util import redis_client

logger = logging.getLogger(__name__)


async def _fe_retrieve_impl(
    query: str,
    layer: str,
    n: int,
    user_id: int,
    namespace: str,
) -> FERetrieveOutput:
    """实际 fe_retrieve 调用 — 通过 gRPC 或 HTTP 调用遗忘引擎"""
    from config import settings
    import httpx

    try:
        async with httpx.AsyncClient(timeout=settings.FE_GRPC_TIMEOUT) as client:
            resp = await client.post(
                f"http://{settings.FE_GRPC_HOST}:{settings.FE_GRPC_PORT}/api/v1/retrieve",
                json={
                    "query": query,
                    "layer": layer,
                    "n": n,
                    "user_id": user_id,
                    "namespace": namespace,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_items = [
                    MemoryItem(
                        id=item.get("id", ""),
                        text=item.get("text", ""),
                        layer=item.get("layer", "semantic"),
                        score=item.get("score", 0.0),
                        created_at=item.get("created_at", ""),
                    )
                    for item in data.get("items", [])
                ]
                content = "\n".join(
                    f"[{item.layer}] {item.text} (score={item.score:.2f})"
                    for item in raw_items
                )
                return FERetrieveOutput(
                    content=content,
                    raw_items=raw_items,
                    retrieved_count=len(raw_items),
                )
    except Exception as e:
        logger.warning(f"[fe_retrieve] gRPC/HTTP failed: {e}")

    # 失败兜底: 从 Redis 缓存读取
    cache_key = f"memory_cache:{namespace}:{user_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        try:
            data = json.loads(cached)
            return FERetrieveOutput(
                content=data.get("content", ""),
                raw_items=[],
                retrieved_count=0,
            )
        except Exception:
            pass

    # 最终兜底: 返回空上下文 (6.6: FE gRPC 不可用 → fe_retrieve 返回空)
    return FERetrieveOutput(content="", raw_items=[], retrieved_count=0)


async def fe_retrieve(
    query: str,
    layer: str,
    n: int,
    user_id: int,
    namespace: str,
) -> FERetrieveOutput:
    """带重试的 fe_retrieve，失败返回空上下文"""
    result = await with_retry(
        "fe_retrieve",
        _fe_retrieve_impl,
        query, layer, n, user_id, namespace,
    )
    if result is None:
        return FERetrieveOutput(content="", raw_items=[], retrieved_count=0)
    return result


async def _fe_ingest_impl(
    text: str,
    role: str,
    session_id: str,
    user_id: int,
    namespace: str,
    importance: float,
) -> FEIngestOutput:
    """实际 fe_ingest 调用 — 失败直接返回，不推队列 (S5-07: 无 worker 消费)"""
    from config import settings
    import httpx
    import uuid

    try:
        async with httpx.AsyncClient(timeout=settings.FE_GRPC_TIMEOUT) as client:
            resp = await client.post(
                f"http://{settings.FE_GRPC_HOST}:{settings.FE_GRPC_PORT}/api/v1/ingest",
                json={
                    "text": text,
                    "role": role,
                    "session_id": session_id,
                    "user_id": user_id,
                    "namespace": namespace,
                    "importance": importance,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return FEIngestOutput(
                    msg_id=data.get("msg_id", str(uuid.uuid4())),
                    success=True,
                )
    except Exception as e:
        logger.warning(f"[fe_ingest] gRPC/HTTP failed: {e}")

    # 失败直接返回，不阻断主流程（不再推未消费的 ingest_queue）
    return FEIngestOutput(msg_id="", success=False)


async def fe_ingest(
    text: str,
    role: str,
    session_id: str,
    user_id: int,
    namespace: str,
    importance: float = 0.5,
) -> FEIngestOutput:
    """带重试的 fe_ingest，失败进入队列不阻断主流程"""
    result = await with_retry(
        "fe_ingest",
        _fe_ingest_impl,
        text, role, session_id, user_id, namespace, importance,
    )
    if result is None:
        # 记录失败日志，不阻断主流程
        logger.error(f"[fe_ingest] all attempts failed for session {session_id}")
        return FEIngestOutput(msg_id="failed", success=False)
    return result


async def _rag_search_impl(
    query: str,
    tenant_id: int,
    top_k: int,
    search_type: str,
) -> RAGSearchOutput:
    """委托给 rag_tool.py 的 rag_search（S5-08: 消重，统一走 rag_tool RRF 融合）"""
    from app.tools.rag_tool import rag_search as _rag_search_raw
    input = RAGSearchInput(
        query=query, tenant_id=tenant_id, top_k=top_k, search_type=search_type,  # type: ignore
    )
    return await _rag_search_raw(input)


async def rag_search(
    query: str,
    tenant_id: int,
    top_k: int = 5,
    search_type: str = "hybrid",
) -> RAGSearchOutput:
    """带重试的 rag_search，失败返回空结果"""
    result = await with_retry(
        "rag_search",
        _rag_search_impl,
        query, tenant_id, top_k, search_type,
    )
    if result is None:
        return RAGSearchOutput(items=[], total=0)
    return result


# S5-08: rag_conflict 统一委托 rag_tool.py，消重双实现
async def _rag_conflict_impl(
    ingredients: list[str],
    user_id: int,
    check_types: list[str],
) -> RAGConflictOutput:
    from app.tools.rag_tool import rag_conflict as _rag_conflict_raw
    from app.tools.models import RAGConflictInput
    input = RAGConflictInput(
        ingredients=ingredients,
        user_id=user_id,
        check_types=check_types,
    )
    return await _rag_conflict_raw(input)


async def rag_conflict(
    ingredients: list[str],
    user_id: int,
    check_types: list[str] | None = None,
) -> RAGConflictOutput:
    """带重试的 rag_conflict，失败返回 has_urgent=false"""
    if check_types is None:
        check_types = ["ingredient_conflict", "skin_sensitivity", "dosage_excess"]
    result = await with_retry(
        "rag_conflict",
        _rag_conflict_impl,
        ingredients, user_id, check_types,
    )
    if result is None:
        return RAGConflictOutput(conflicts=[], has_urgent=False)
    return result


async def _product_crud_impl(
    action: str,
    tenant_id: int,
    data: dict,
    product_id: int | None,
    query: str | None,
) -> ProductCRUDOutput:
    """实际 product_crud 调用"""
    from db_util import db

    try:
        if action == "create":
            row = await db.fetchrow(
                """
                INSERT INTO products (tenant_id, name, brand, category, ingredients, description)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, name, brand, category, ingredients, description
                """,
                tenant_id,
                data.get("name", ""),
                data.get("brand", ""),
                data.get("category", ""),
                json.dumps(data.get("ingredients", []), ensure_ascii=False),
                data.get("description", ""),
            )
            product = ProductItem(
                id=row["id"],
                name=row["name"],
                brand=row.get("brand", ""),
                category=row.get("category", ""),
                ingredients=json.loads(row.get("ingredients", "[]")) if isinstance(row.get("ingredients"), str) else (row.get("ingredients") or []),
                description=row.get("description", ""),
            )
            return ProductCRUDOutput(success=True, action="create", products=[product], affected_rows=1)

        elif action == "read":
            row = await db.fetchrow(
                "SELECT id, name, brand, category, ingredients, description FROM products WHERE id = $1 AND tenant_id = $2",
                product_id, tenant_id,
            )
            if row:
                ingredients_list = json.loads(row["ingredients"]) if isinstance(row.get("ingredients"), str) else (row.get("ingredients") or [])
                product = ProductItem(
                    id=row["id"],
                    name=row["name"],
                    brand=row.get("brand", ""),
                    category=row.get("category", ""),
                    ingredients=ingredients_list,
                    description=row.get("description", ""),
                )
                return ProductCRUDOutput(success=True, action="read", products=[product], affected_rows=1)
            return ProductCRUDOutput(success=False, action="read", products=[], affected_rows=0, error="product not found")

        elif action == "update":
            if not product_id:
                return ProductCRUDOutput(success=False, action="update", products=[], affected_rows=0, error="product_id required")
            result = await db.execute(
                """
                UPDATE products SET name=$3, brand=$4, category=$5, ingredients=$6, description=$7
                WHERE id=$1 AND tenant_id=$2
                """,
                product_id, tenant_id,
                data.get("name", ""),
                data.get("brand", ""),
                data.get("category", ""),
                json.dumps(data.get("ingredients", []), ensure_ascii=False),
                data.get("description", ""),
            )
            affected = 1 if result and "UPDATE 1" in str(result) else 0
            return ProductCRUDOutput(success=affected > 0, action="update", products=[], affected_rows=affected)

        elif action == "list":
            rows = await db.fetch(
                "SELECT id, name, brand, category, ingredients, description FROM products WHERE tenant_id = $1 ORDER BY id DESC LIMIT 20",
                tenant_id,
            )
            products = [
                ProductItem(
                    id=row["id"],
                    name=row["name"],
                    brand=row.get("brand", ""),
                    category=row.get("category", ""),
                    ingredients=json.loads(row["ingredients"]) if isinstance(row.get("ingredients"), str) else (row.get("ingredients") or []),
                    description=row.get("description", ""),
                )
                for row in rows
            ]
            return ProductCRUDOutput(success=True, action="list", products=products, affected_rows=len(products))

        elif action == "search":
            rows = await db.fetch(
                """
                SELECT id, name, brand, category, ingredients, description
                FROM products
                WHERE tenant_id = $1 AND (name ILIKE '%' || $2 || '%' OR description ILIKE '%' || $2 || '%')
                LIMIT 10
                """,
                tenant_id, query or "",
            )
            products = [
                ProductItem(
                    id=row["id"],
                    name=row["name"],
                    brand=row.get("brand", ""),
                    category=row.get("category", ""),
                    ingredients=json.loads(row["ingredients"]) if isinstance(row.get("ingredients"), str) else (row.get("ingredients") or []),
                    description=row.get("description", ""),
                )
                for row in rows
            ]
            return ProductCRUDOutput(success=True, action="search", products=products, affected_rows=len(products))

        else:
            return ProductCRUDOutput(success=False, action=action, products=[], affected_rows=0, error=f"unknown action: {action}")

    except Exception as e:
        logger.error(f"[product_crud] {action} failed: {e}")
        return ProductCRUDOutput(success=False, action=action, products=[], affected_rows=0, error=str(e))


async def product_crud(
    action: str,
    tenant_id: int,
    data: dict | None = None,
    product_id: int | None = None,
    query: str | None = None,
) -> ProductCRUDOutput:
    """带重试的 product_crud，失败返回错误"""
    if data is None:
        data = {}
    result = await with_retry(
        "product_crud",
        _product_crud_impl,
        action, tenant_id, data, product_id, query,
    )
    if result is None:
        return ProductCRUDOutput(success=False, action=action, products=[], affected_rows=0, error="crud_unavailable")
    return result


async def _profile_query_impl(
    user_id: int,
    include: list[str],
) -> ProfileQueryOutput:
    """实际 profile_query 调用"""
    from db_util import db

    try:
        row = await db.fetchrow(
            """
            SELECT skin_type, concerns AS skin_concerns, allergies,
                   NULL AS current_products,
                   CASE WHEN skin_type IS NOT NULL THEN 0.75 ELSE 0.0 END AS profile_completeness
            FROM skin_profiles
            WHERE user_id = $1
            """,
            user_id,
        )
        if row:
            return ProfileQueryOutput(
                skin_type=row.get("skin_type"),
                skin_concerns=row.get("skin_concerns", []) or [],
                allergies=row.get("allergies", []) or [],
                current_products=row.get("current_products", []) or [],
                profile_completeness=float(row.get("profile_completeness", 0.0)),
            )
        return ProfileQueryOutput(profile_completeness=0.0)

    except Exception as e:
        logger.warning(f"[profile_query] failed: {e}")

    return ProfileQueryOutput(profile_completeness=0.0)


async def profile_query(
    user_id: int,
    include: list[str] | None = None,
) -> ProfileQueryOutput:
    """带重试的 profile_query，失败返回空 profile"""
    if include is None:
        include = ["skin_type", "current_products", "allergies", "concerns"]
    result = await with_retry(
        "profile_query",
        _profile_query_impl,
        user_id, include,
    )
    if result is None:
        return ProfileQueryOutput(profile_completeness=0.0)
    return result
