"""
Tool 层数据模型 — 所有 6 个 Tool 的 Pydantic 输入/输出
严格对应 Step 5 文档定义
"""
from pydantic import BaseModel, Field
from typing import Literal


# ============================================================
# 5.2 fe_retrieve — 读记忆上下文
# ============================================================

class MemoryItem(BaseModel):
    id: str
    text: str
    layer: str
    score: float
    created_at: str = ""


class FERetrieveInput(BaseModel):
    query: str = Field(..., max_length=200, description="检索关键词")
    layer: Literal["semantic", "episodic", "preference", "all"] = "all"
    n: int = Field(default=5, ge=1, le=20)
    user_id: int
    namespace: str = Field(..., description="格式: tenant:{tenant_id}:agent:{agent_type}")


class FERetrieveOutput(BaseModel):
    content: str = Field(..., description="格式化后可直接注入 prompt 的文本")
    raw_items: list[MemoryItem] = []
    retrieved_count: int = 0


# ============================================================
# 5.3 fe_ingest — 写记忆
# ============================================================

class FEIngestInput(BaseModel):
    text: str = Field(..., max_length=4000)
    role: Literal["user", "assistant"]
    session_id: str
    user_id: int
    namespace: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class FEIngestOutput(BaseModel):
    msg_id: str
    success: bool


# ============================================================
# 5.4 rag_search — 知识检索
# ============================================================

class KnowledgeItem(BaseModel):
    id: int
    name: str
    brand: str = ""
    category: str = ""
    ingredients: list[str] = []
    description: str = ""
    score: float = 0.0


class RAGSearchInput(BaseModel):
    query: str
    tenant_id: int
    top_k: int = Field(default=5, ge=1, le=20)
    search_type: Literal["hybrid", "semantic", "keyword"] = "hybrid"


class RAGSearchOutput(BaseModel):
    items: list[KnowledgeItem] = []
    total: int = 0


# ============================================================
# 5.5 rag_conflict — 成分冲突检测
# ============================================================

class ConflictItem(BaseModel):
    conflict_type: str
    severity: str  # high | medium | low
    description: str
    ingredients_involved: list[str] = []
    suggestion: str = ""


class RAGConflictInput(BaseModel):
    ingredients: list[str]
    user_id: int
    check_types: list[str] = Field(
        default=["ingredient_conflict", "skin_sensitivity", "dosage_excess"]
    )


class RAGConflictOutput(BaseModel):
    conflicts: list[ConflictItem] = []
    has_urgent: bool = False  # 有 high severity 冲突时为 true


# ============================================================
# 5.6 product_crud — 产品录入/查询
# ============================================================

class ProductCRUDInput(BaseModel):
    action: Literal["create", "read", "update", "list", "search"]
    tenant_id: int
    data: dict = {}
    product_id: int | None = None
    query: str | None = None


class ProductItem(BaseModel):
    id: int
    name: str
    brand: str = ""
    category: str = ""
    ingredients: list[str] = []
    description: str = ""


class ProductCRUDOutput(BaseModel):
    success: bool
    action: str
    products: list[ProductItem] = []
    affected_rows: int = 0
    error: str | None = None


# ============================================================
# 5.7 profile_query — 用户肤质/档案查询
# ============================================================

class ProfileQueryInput(BaseModel):
    user_id: int
    include: list[str] = Field(
        default=["skin_type", "current_products", "allergies", "concerns"]
    )


class ProfileQueryOutput(BaseModel):
    skin_type: str | None = None
    skin_concerns: list[str] = []
    allergies: list[str] = []
    current_products: list[dict] = []
    profile_completeness: float = 0.0  # 0.0-1.0，用于判断是否需要问卷
