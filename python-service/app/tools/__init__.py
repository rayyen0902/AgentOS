"""
Tool 层 — 6 个 Tool + 工具模块
Step 5 规范实现
"""
from app.tools.registry import (
    fe_retrieve,
    fe_ingest,
    fe_ingest_async,
    rag_search,
    rag_conflict,
    product_crud,
    profile_query,
    retrieve_for_agent,
    MemoryContext,
)
from app.tools.models import (
    FERetrieveInput, FERetrieveOutput, MemoryItem,
    FEIngestInput, FEIngestOutput,
    RAGSearchInput, RAGSearchOutput, KnowledgeItem,
    RAGConflictInput, RAGConflictOutput, ConflictItem,
    ProductCRUDInput, ProductCRUDOutput, ProductItem,
    ProfileQueryInput, ProfileQueryOutput,
)
# S5-13: Memory Consolidation 实现在 app/agents/memory_consolidation.py
from app.agents.memory_consolidation import MemoryConsolidation, trigger_memory_consolidation_async
