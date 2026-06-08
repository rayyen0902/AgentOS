# Step 5 消项清单

> 负责：Tool 层（fe_tool / rag_tool / product_tool / profile_tool / embedding）
> GitHub Issue: #10, #13, #15, #21

---

## 🔴 Critical — #10 (1 条)

- [ ] **S5-01** `python-service/app/tools/fe_client.py` — HTTP POST + JSON 而非 gRPC + protobuf 调用 `knownot.cc:50052`。标准 gRPC 服务器不接受 HTTP/1.1 JSON。需获取 .proto 文件 → 生成 Python stub → 重写为 gRPC 调用。保留 HTTP 降级通道

---

## 🟠 High — #13, #15, #21 (7 条)

- [ ] **S5-02** `python-service/app/tools/product_tool.py:114` — `_product_read` SQL `SELECT ... WHERE id = $1` 缺 `AND tenant_id = $2`。租户 A 可读租户 B 产品
- [ ] **S5-03** `python-service/app/tools/product_tool.py:152` — `_product_update` SQL `UPDATE ... WHERE id = $1` 缺 `AND tenant_id = $2`。租户 A 可改租户 B 产品
- [ ] **S5-04** `python-service/app/agents/tool_invoker.py:329` — `_rag_conflict_impl` SQL 引用了 `c.ingredients_involved`，但 PRD 定义的 `knowledge.product_conflicts` 表无此列
- [ ] **S5-05** `python-service/app/agents/tool_invoker.py:514` — `profile_query_impl` 查了 `FROM user_profiles`，但 PRD 13.4 只有 `skin_profiles` 表
- [ ] **S5-06** `python-service/app/agents/tool_invoker.py:302` — `_rag_conflict_impl` SQL 查询 products 不加 `tenant_id` 过滤，跨租户冲突检测
- [ ] **S5-07** `python-service/app/tools/tool_invoker.py:152` — FE 不可用时 push 到 Redis `ingest_queue`，但无 worker 消费此队列，消息永久堆积
- [ ] **S5-08** `python-service/app/tools/tool_invoker.py` + `python-service/app/tools/rag_tool.py` — 冲突检测逻辑完全重复两遍。`tool_invoker._rag_search_impl` 绕过 `rag_tool.py` 的 RRF 融合。合并为单一实现

---

## 🟡 Medium (4 条)

- [ ] **S5-09** `python-service/app/tools/registry.py` — `fe_ingest` 声明返回 `-> None`，调用方期望 `FEIngestOutput`。类型不匹配
- [ ] **S5-10** `python-service/config.py` — `FE_GRPC_TIMEOUT` 配置存 `"5s"` 字符串，代码硬编码 `5.0` float。统一为解析后的秒数
- [ ] **S5-11** `python-service/app/agents/tool_invoker.py:303` — `_rag_conflict_impl` 动态 SQL 参数编号用字符串拼接 `${len(ingredients)+1}`，ingredients 为空时 `$1` 与其他绑定冲突
- [ ] **S5-12** `python-service/app/tools/retry_util.py` — 固定间隔重试，PRD 20.2 规定指数退避（1s/2s/4s）。改为 `delay * (2 ** retry_count)`

---

## 🟢 Low (5 条)

- [ ] **S5-13** `python-service/app/tools/models.py` — `MemoryItem` / `KnowledgeItem` / `ConflictItem` 类型未在任何地方定义（PRD 引用但无定义）
- [ ] **S5-14** Step 5 文档 — RRF `get_product()` 伪代码函数来源未定义。应改为 `product_crud(read)` 或直接 SQL
- [ ] **S5-15** `python-service/config.py:45` — `EMBEDDING_DIMS` 校验 `!= 1024` 直接 raise。应改 warning 而非 hard error
- [ ] **S5-16** `python-service/db_util.py` — 无 `async with db.transaction()` 事务支持
- [ ] **S5-17** `python-service/db_util.py` — `min_size=2, max_size=10` 硬编码。应从 config 读取
