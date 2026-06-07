# Step 5 消项清单

> 你负责：Tool 层（fe_tool / rag_tool / product_tool / profile_tool / embedding）

---

## #10 【Critical】HTTP REST 而非 gRPC 调用 FE，无 .proto 文件

**文件**: `python-service/app/tools/fe_client.py`

**问题**: PRD 规定 gRPC 调 `knownot.cc:50052`，代码用 HTTP POST + JSON。标准 gRPC 服务器不接受 HTTP/1.1 JSON。

**修复**: 
1. 获取 FE 的 `.proto` 文件
2. 用 `grpcio` + `grpcio-tools` 生成 Python stub
3. 重写 `fe_retrieve` / `fe_ingest` 为 gRPC 调用
4. 保留 HTTP 降级通道（gRPC 不可用时降级 REST）

---

## #13 【High】跨租户数据泄露: product + rag_conflict SQL 无 tenant_id 过滤

**文件**: `python-service/app/tools/product_tool.py`, `python-service/app/agents/tool_invoker.py`

**修复**:
1. `product_tool.py:114` — `_product_read` SQL 加 `AND tenant_id = $2`
2. `product_tool.py:152` — `_product_update` SQL 加 `AND tenant_id = $2`
3. `tool_invoker.py:302` — `_rag_conflict_impl` SQL 加 `AND p.tenant_id = $N`

---

## #15 【High】SQL 引用了不存在的列 + 查了不存在的表

**文件**: `python-service/app/agents/tool_invoker.py`

**修复**:
1. **行 329**: `c.ingredients_involved` 列不存在——对照 `knowledge.product_conflicts` 表结构修正 SQL
2. **行 514**: `FROM user_profiles` → `FROM skin_profiles`（PRD 13.4 规定的表名）

---

## #21 【High】fe_ingest 离线队列无消费者 + 配置/类型不一致 + 双边重复实现

**文件**: 多个

| 文件 | 问题 | 修复 |
|------|------|------|
| `tools/tool_invoker.py:152` | `ingest_queue` lpush 无 worker | 加后台 asyncio task 定期消费+重试 |
| `tools/registry.py` | `fe_ingest` 声明返回 None | 改为返回 `FEIngestOutput` |
| `config.py` | `FE_GRPC_TIMEOUT` 存 `"5s"` 字符串 | 解析为秒数，或代码统一读配置 |
| `tools/tool_invoker.py` + `tools/rag_tool.py` | 冲突检测完全重复 | 合并到 `rag_tool.py` 单一实现，tool_invoker 调 rag_tool |

---

## 关联：低优先级

- `MemoryItem` / `KnowledgeItem` / `ConflictItem` 类型在 `tools/models.py` 中明确定义
- RRF `get_product()` 改为调 `product_crud(action="read", product_id=id)` 或直接 SQL
- `retry_util.py` 改为指数退避（PRD 20.2: 1s/2s/4s）
