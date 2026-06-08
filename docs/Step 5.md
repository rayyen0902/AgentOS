# Step 5：Tool 层

> **上下文范围**：PRD 第 5.1（Tool 接口）、第 5.1.2（重试策略）、第 7 节（Memory OS）、第 9 节（RAG）
> **前置依赖**：Step 1（DB + Redis + FE proto）、Step 2（BaseAgent 接口）
> **完成标准**：6 个 Tool 全部可用，gRPC 调用 FE 正常，pgvector 混合检索返回结果，Embedding 缓存命中

---

## 5.1 Tool 列表与职责

| Tool | 功能 | 输入 | 输出 |
|------|------|------|------|
| `fe_retrieve` | 读记忆上下文 | query | 格式化文本 |
| `fe_ingest` | 写记忆 | text + role + session_id | msg_id |
| `rag_search` | 知识检索 | query | 知识条目列表 |
| `rag_conflict` | 成分冲突检测 | product/ingredient | 冲突规则 |
| `product_crud` | 产品录入/查询 | action + data | 产品列表 |
| `profile_query` | 用户肤质/档案查询 | user_id | 肤质+在用产品 |

---

## 5.2 fe_retrieve（读记忆上下文）

```python
class FERetrieveInput(BaseModel):
    query: str                          # 检索关键词，最长 200 字
    layer: Literal["semantic", "episodic", "preference", "all"] = "all"
    n: int = Field(default=5, ge=1, le=20)
    user_id: int
    namespace: str                      # 格式: "tenant:{tenant_id}:agent:{agent_type}"

class FERetrieveOutput(BaseModel):
    content: str                        # 格式化后可直接注入 prompt 的文本
    raw_items: list[MemoryItem]
    retrieved_count: int
```

- **gRPC 调用**：FE 服务（knownot.cc:50052）
- **超时**：5s
- **重试**：2 次，间隔 500ms
- **兜底**：返回空上下文，Agent 继续无记忆模式运行

---

## 5.3 fe_ingest（写记忆）

```python
class FEIngestInput(BaseModel):
    text: str                           # 最长 4000 字
    role: Literal["user", "assistant"]
    session_id: str
    user_id: int
    namespace: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)

class FEIngestOutput(BaseModel):
    msg_id: str
    success: bool
```

- **重试**：3 次，间隔 1s
- **兜底**：记录失败日志，不阻断主流程
- **异步**：使用 `asyncio.create_task`，不阻塞 Agent 响应

---

## 5.4 rag_search（知识检索）

```python
class RAGSearchInput(BaseModel):
    query: str
    tenant_id: int
    top_k: int = Field(default=5, ge=1, le=20)
    search_type: Literal["hybrid", "semantic", "keyword"] = "hybrid"

class RAGSearchOutput(BaseModel):
    items: list[KnowledgeItem]
    total: int
```

### 混合检索实现

```python
def hybrid_search(query: str, tenant_id: int, top_k: int = 5) -> list[Product]:
    vec = embed_single(query)
    semantic = pgvector_search(vec, tenant_id, limit=top_k * 2)
    filters = extract_filters(query)
    keyword = sql_filter_search(filters, tenant_id, limit=top_k)
    return rrf_merge(semantic, keyword, top_k)
```

### RRF 融合

```python
def rrf_merge(semantic: list, keyword: list, top_k: int, k: int = 60) -> list:
    """Reciprocal Rank Fusion"""
    scores = {}
    for rank, item in enumerate(semantic):
        scores[item.id] = scores.get(item.id, 0) + 1 / (k + rank + 1)
    for rank, item in enumerate(keyword):
        scores[item.id] = scores.get(item.id, 0) + 1 / (k + rank + 1)
    sorted_ids = sorted(scores, key=scores.get, reverse=True)
    # S5-14: get_product() 替换为 product_crud(read) 或直接 SQL SELECT
    return [product_crud(ProductCRUDInput(action="read", tenant_id=tid, product_id=id)) for id in sorted_ids[:top_k]]
```

- **重试**：2 次，间隔 500ms
- **兜底**：返回空结果，Agent 告知用户"暂时无法查询知识库"
- **降级**：pgvector 索引损坏 → 降级为仅 keyword 检索

---

## 5.5 rag_conflict（成分冲突检测）

```python
class RAGConflictInput(BaseModel):
    ingredients: list[str]
    user_id: int
    check_types: list[str] = ["ingredient_conflict", "skin_sensitivity", "dosage_excess"]

class RAGConflictOutput(BaseModel):
    conflicts: list[ConflictItem]
    has_urgent: bool                    # 有 high severity 冲突时为 true
```

- **数据来源**：`knowledge.conflict_rules` + `knowledge.product_conflicts`
- **重试**：2 次，间隔 500ms
- **兜底**：返回 `has_urgent=false`（降级，不阻断推荐）

---

## 5.6 product_crud（产品录入/查询）

```python
class ProductCRUDInput(BaseModel):
    action: Literal["create", "read", "update", "list", "search"]
    tenant_id: int
    data: dict = {}
    product_id: int | None = None
    query: str | None = None
```

- **重试**：1 次
- **兜底**：返回错误，上抛 Agent 处理
- **create/update**：写入后触发 Embedding 生成（异步）

---

## 5.7 profile_query（用户肤质/档案查询）

```python
class ProfileQueryInput(BaseModel):
    user_id: int
    include: list[str] = ["skin_type", "current_products", "allergies", "concerns"]

class ProfileQueryOutput(BaseModel):
    skin_type: str | None
    skin_concerns: list[str]
    allergies: list[str]
    current_products: list[dict]
    profile_completeness: float         # 0.0-1.0，用于判断是否需要问卷
```

- **重试**：2 次，间隔 500ms
- **兜底**：返回空 profile，Agent 改走问卷路径

---

## 5.8 重试策略汇总

| Tool | 最大重试 | 重试间隔 | 失败兜底 |
|------|---------|---------|----------|
| `fe_retrieve` | 2 次 | 500ms | 返回空上下文，Agent 继续无记忆模式 |
| `fe_ingest` | 3 次 | 1s | 记录失败日志，不阻断主流程 |
| `rag_search` | 2 次 | 500ms | 返回空结果，Agent 告知用户"暂时无法查询知识库" |
| `rag_conflict` | 2 次 | 500ms | 返回 has_urgent=false（降级） |
| `product_crud` | 1 次 | 立即 | 返回错误，上抛 Agent 处理 |
| `profile_query` | 2 次 | 500ms | 返回空 profile，Agent 改走问卷路径 |

---

## 5.9 Embedding 服务 + Redis 缓存

- 模型：`text-embedding-v4`，维度 1024
- 缓存 Key：`embed_cache:{sha256(text)}`，TTL 3600s
- 缓存命中 → 直接返回向量，跳过 API 调用
- 产品向量存储：`products.embedding` 列（pgvector）

---

## 5.10 Memory OS 三层结构

```
Episodic Memory（情节记忆）
  "2026-05-01 用户咨询爆痘，推荐了A方案，用户采纳"
  → 用途：知道用户经历了什么，避免重复推荐

Semantic Memory（语义记忆）
  "用户是敏感肌，对烟酰胺耐受性良好，偏好日系品牌"
  → 用途：快速判断适配/禁忌

Preference Memory（偏好记忆）
  "喜欢喷雾质地，价格敏感度中（200-500元）"
  → 用途：影响推荐排序和话术风格
```

### Agent 分层调用策略

```python
async def retrieve_for_agent(query: str, agent_type: str) -> MemoryContext:
    if agent_type == "workshop":
        return MemoryContext(
            semantic=await fe.retrieve(query, layer="semantic"),
            preference=await fe.retrieve(query, layer="preference"),
            episodic=await fe.retrieve(query, layer="episodic", n=3),
        )
    elif agent_type in ("diagnosis", "front"):
        return MemoryContext(
            semantic=await fe.retrieve(query, layer="semantic"),
            episodic=await fe.retrieve(query, layer="episodic", n=5),
        )
```

### Memory Consolidation 规则

- 触发时机：每次对话结束后，由 Reflection Agent 异步触发
- 窗口：7 天内出现 ≥ 3 次的相同语义事实 → 从 Episodic 提升至 Semantic
- 写入：通过 `fe_ingest` Tool，`importance = 0.8`
- 去重：相同 namespace + 相似度 > 0.95 的 Semantic 条目合并（FE 侧负责）

---

## 5.11 验收标准

- [ ] `fe_retrieve` gRPC 调用 FE 成功，返回记忆上下文
- [ ] `fe_ingest` gRPC 调用 FE 成功，返回 msg_id
- [ ] `rag_search` hybrid_search + RRF 融合返回语义相关产品
- [ ] `rag_conflict` 成分冲突检测正常
- [ ] `product_crud` 5 种 action 全部正常
- [ ] `profile_query` 返回肤质+在用产品+profile_completeness
- [ ] 所有 Tool 错误重试符合策略表
- [ ] 所有 Tool 失败兜底逻辑生效（不阻断主流程）
- [ ] Embedding Redis 缓存命中率 > 0（测试环境验证）
- [ ] Memory Consolidation 触发逻辑实现（Reflection Agent 调用侧）
