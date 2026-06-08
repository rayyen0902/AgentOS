# Step 5 消项清单

> 负责：Tool 层（fe_tool / rag_tool / product_tool / profile_tool / embedding）
> GitHub Issue: #10, #13, #15, #21

---

## 🔴 Critical — #10 (1 条)

- [x] **S5-01** `python-service/app/tools/fe_client.py` — fixed: gRPC 优先 (ForgettingEngineStub, proto stub fe_service_pb2.py/fe_service_pb2_grpc.py) + HTTP JSON 降级通道保留

---

## 🟠 High — #13, #15, #21 (7 条)

- [x] **S5-02** `python-service/app/tools/product_tool.py:114` — fixed: `_product_read` SQL 已加 `AND tenant_id = $2`，租户隔离
- [x] **S5-03** `python-service/app/tools/product_tool.py:152` — fixed: `_product_update` SQL 已加 `AND tenant_id = ${idx+1}`，租户隔离
- [x] **S5-04** `python-service/app/agents/tool_invoker.py:329` — fixed: `_rag_conflict_impl` 已委托 rag_tool.py，不再直接引用 `c.ingredients_involved` 列
- [x] **S5-05** `python-service/app/agents/tool_invoker.py:514` — fixed: `profile_query_impl` 已查询 `skin_profiles` 表
- [x] **S5-06** `python-service/app/agents/tool_invoker.py:302` — fixed: `_rag_conflict_impl` 已委托 rag_tool.py，rag_tool 带 tenant_id 过滤
- [x] **S5-07** `python-service/app/tools/tool_invoker.py:152` — fixed: FE 不可用时直接返回失败 (不再推无 worker 的 ingest_queue)
- [x] **S5-08** `python-service/app/tools/tool_invoker.py` + `python-service/app/tools/rag_tool.py` — fixed: `tool_invoker._rag_search_impl` 和 `_rag_conflict_impl` 均委托 rag_tool.py 单一实现（RRF 融合/冲突检测）

---

## 🟡 Medium (4 条)

- [x] **S5-09** `python-service/app/tools/registry.py` — fixed: `fe_ingest` 返回 `FEIngestOutput` 类型
- [x] **S5-10** `python-service/config.py` — fixed: config `FE_GRPC_TIMEOUT` 统一解析为 float 秒；fe_client.py 使用 `settings.FE_GRPC_TIMEOUT`；agents/tool_invoker.py 使用 `settings.FE_GRPC_TIMEOUT`
- [x] **S5-11** `python-service/app/agents/tool_invoker.py:303` — fixed: `_rag_conflict_impl` 已委托 rag_tool.py，无动态参数编号拼接风险
- [x] **S5-12** `python-service/app/tools/retry_util.py` — fixed: `with_retry` 使用指数退避 `base_delay * (2 ** attempt)`

---

## 🟢 Low (5 条)

- [x] **S5-13** `python-service/app/tools/models.py` — fixed: `MemoryItem` / `KnowledgeItem` / `ConflictItem` 已在 models.py 中定义为 Pydantic BaseModel
- [x] **S5-14** Step 5 文档 — fixed: RRF 伪代码 `get_product(id)` 替换为 `product_crud(ProductCRUDInput(action="read",...))`，注明可降级为直接 SQL SELECT
- [x] **S5-15** `python-service/config.py:45` — fixed: `EMBEDDING_DIMS != 1024` 改为 `warnings.warn()` 而非 `raise`
- [x] **S5-16** `python-service/db_util.py` — fixed: 新增 `async with db.transaction()` 事务上下文管理器（asyncpg transaction）
- [x] **S5-17** `python-service/db_util.py` — fixed: 连接池 `min_size`/`max_size` 从 `settings.DB_POOL_MIN_SIZE` / `settings.DB_POOL_MAX_SIZE` 读取
