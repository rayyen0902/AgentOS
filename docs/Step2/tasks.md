# Step 2 消项清单

> 你负责：FastAPI 路由 + BaseAgent + Telemetry + Capability Registry

---

## #1 【Critical】路由 3 秒超时包住整个 orchestrator，子 Agent 永远超时

**文件**: `python-service/app/api/routes.py:207`

**问题**: `asyncio.wait_for(..., timeout_s=3.0)` 包住了整个 orchestrator 调用，子 Agent 实际需要 20-600s。

**修复**: 3s 超时只应用于前台 Agent 意图分类阶段，子 Agent 委派结果通过后台 goroutine/SSE 异步返回。routes.py 应在收到 orchestrator 的 immediate_reply 后即返回 200，子 Agent 结果走异步通知。

---

## #4 【Critical】Observability 遥测从未落库，alert 永远不触发

**文件**: `python-service/app/observation/telemetry.py`

**问题**: `finish_trace()` 只设 total_ms，从未调 `flush_to_db()`。trace 全部存内存→进程重启丢失→`observation_traces` 表空→告警规则零数据→静默失效。

**修复**: 在 routes.py 的响应返回前调用 `await telemetry.flush_to_db(trace_id)`，或在 `finish_trace` 内部自动 flush。

---

## 关联：低优先级改进

- `BaseAgent.name` 改为 `@abstractmethod` property，防止子类忘记设置导致 AttributeError
- `SessionContext` / `AgentResult` 的 `reply` 字段加 max_length=1000 校验
