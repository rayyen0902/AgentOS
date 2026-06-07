"""
Tool 层统一入口 — 6 个 Tool 的注册 + 重试 + 兜底
严格对应 Step 5 文档
"""
import asyncio
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
)
from app.tools.fe_client import fe_retrieve as _fe_retrieve_raw, fe_ingest as _fe_ingest_raw
from app.tools.rag_tool import rag_search as _rag_search_raw, rag_conflict as _rag_conflict_raw
from app.tools.product_tool import product_crud as _product_crud_raw, profile_query as _profile_query_raw
from app.tools.retry_util import with_retry

logger = logging.getLogger(__name__)


# ============================================================
# 5.2 fe_retrieve — 读记忆上下文
# ============================================================

async def fe_retrieve(input: FERetrieveInput) -> FERetrieveOutput:
    """
    重试 2次，间隔 500ms
    兜底: 返回空上下文，Agent 继续无记忆模式运行
    """
    result = await with_retry("fe_retrieve", _fe_retrieve_raw, input)
    if result is None:
        # 兜底
        return FERetrieveOutput(content="", raw_items=[], retrieved_count=0)
    return result


# ============================================================
# 5.3 fe_ingest — 写记忆
# ============================================================

async def fe_ingest(input: FEIngestInput) -> None:
    """
    重试 3次，间隔 1s
    兜底: 记录失败日志，不阻断主流程
    异步: 使用 asyncio.create_task 调用，不阻塞 Agent 响应
    """
    try:
        result = await with_retry("fe_ingest", _fe_ingest_raw, input)
        if result is None:
            logger.error(f"[fe_ingest] failed after all retries for session={input.session_id}")
    except Exception as e:
        logger.error(f"[fe_ingest] failed for session={input.session_id}: {e}")


async def fe_ingest_async(input: FEIngestInput) -> None:
    """外部调用：使用 asyncio.create_task 异步写记忆，不阻塞 Agent 响应"""
    asyncio.create_task(fe_ingest(input))


# ============================================================
# 5.4 rag_search — 知识检索
# ============================================================

async def rag_search(input: RAGSearchInput) -> RAGSearchOutput:
    """
    重试 2次，间隔 500ms
    兜底: 返回空结果，Agent 告知用户"暂时无法查询知识库"
    """
    result = await with_retry("rag_search", _rag_search_raw, input)
    if result is None:
        return RAGSearchOutput(items=[], total=0)
    return result


# ============================================================
# 5.5 rag_conflict — 成分冲突检测
# ============================================================

async def rag_conflict(input: RAGConflictInput) -> RAGConflictOutput:
    """
    重试 2次，间隔 500ms
    兜底: 返回 has_urgent=false（降级，不阻断推荐）
    """
    result = await with_retry("rag_conflict", _rag_conflict_raw, input)
    if result is None:
        return RAGConflictOutput(conflicts=[], has_urgent=False)
    return result


# ============================================================
# 5.6 product_crud — 产品录入/查询
# ============================================================

async def product_crud(input: ProductCRUDInput) -> ProductCRUDOutput:
    """
    重试 1次，无间隔
    兜底: 返回错误，上抛 Agent 处理
    """
    result = await with_retry("product_crud", _product_crud_raw, input)
    if result is None:
        return ProductCRUDOutput(
            success=False,
            action=input.action,
            error="Product CRUD failed after retries",
        )
    return result


# ============================================================
# 5.7 profile_query — 用户肤质/档案查询
# ============================================================

async def profile_query(input: ProfileQueryInput) -> ProfileQueryOutput:
    """
    重试 2次，间隔 500ms
    兜底: 返回空 profile，Agent 改走问卷路径
    """
    result = await with_retry("profile_query", _profile_query_raw, input)
    if result is None:
        return ProfileQueryOutput(
            skin_type=None,
            skin_concerns=[],
            allergies=[],
            current_products=[],
            profile_completeness=0.0,
        )
    return result


# ============================================================
# 5.10 Memory OS 三层结构 — Agent 分层调用策略
# ============================================================

from dataclasses import dataclass


@dataclass
class MemoryContext:
    semantic: FERetrieveOutput
    preference: FERetrieveOutput
    episodic: FERetrieveOutput


async def retrieve_for_agent(query: str, user_id: int, namespace: str, agent_type: str) -> MemoryContext:
    """
    Agent 分层调用策略 — Step 5 文档 5.10
    workshop: semantic + preference + episodic(n=3)
    diagnosis/front: semantic + episodic(n=5)
    """
    if agent_type == "workshop":
        semantic = await fe_retrieve(FERetrieveInput(
            query=query, layer="semantic", n=5, user_id=user_id, namespace=namespace,
        ))
        preference = await fe_retrieve(FERetrieveInput(
            query=query, layer="preference", n=5, user_id=user_id, namespace=namespace,
        ))
        episodic = await fe_retrieve(FERetrieveInput(
            query=query, layer="episodic", n=3, user_id=user_id, namespace=namespace,
        ))
        return MemoryContext(semantic=semantic, preference=preference, episodic=episodic)

    elif agent_type in ("diagnosis", "front"):
        semantic = await fe_retrieve(FERetrieveInput(
            query=query, layer="semantic", n=5, user_id=user_id, namespace=namespace,
        ))
        episodic = await fe_retrieve(FERetrieveInput(
            query=query, layer="episodic", n=5, user_id=user_id, namespace=namespace,
        ))
        return MemoryContext(
            semantic=semantic,
            preference=FERetrieveOutput(content="", raw_items=[], retrieved_count=0),
            episodic=episodic,
        )

    # default: semantic only
    semantic = await fe_retrieve(FERetrieveInput(
        query=query, layer="all", n=5, user_id=user_id, namespace=namespace,
    ))
    return MemoryContext(
        semantic=semantic,
        preference=FERetrieveOutput(content="", raw_items=[], retrieved_count=0),
        episodic=FERetrieveOutput(content="", raw_items=[], retrieved_count=0),
    )
