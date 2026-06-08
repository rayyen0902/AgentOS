# Step 2 消项清单

> 负责：FastAPI 路由 + BaseAgent + Telemetry + Capability Registry
> GitHub Issue: #1, #4, #11(Step 2 部分)

---

## 🔴 Critical — #1, #4 (2 条)

- [x] **S2-02** `python-service/app/api/routes.py` — `finish_trace()` 从未调 `flush_to_db()`。所有 trace 存内存不落库，告警规则基于空表永远不触发。✅ **已修**: 所有返回路径前加 `await telemetry.flush_to_db(trace_id)`
- [x] **S2-01** `python-service/app/api/routes.py` — `asyncio.wait_for(3.0s)` 包住整个 orchestrator，子 Agent 需 20-600s 永远超时。✅ **已修**: 3s 仅前台意图分类；超时返回 `done=False`，子 Agent 异步继续

---

## 🟠 High (0 条)

---

## 🟡 Medium (5 条)

- [x] **S2-03** `python-service/app/api/routes.py` — `_handle_resume` 中 `agent_state.get("current_agent", "workshop")` 默认 workshop。中断后状态丢失时错误路由到配药师。✅ **已修**: 校验 `_VALID_AGENTS`，缺失/非法时返回 "会话状态已丢失"
- [x] **S2-04** `python-service/app/api/routes.py` + `main.py` — 响应格式不一致。✅ **已修**: error 统一在 `data.error` 内层，全局异常 handler 保持 `data:null`
- [x] **S2-05** `python-service/app/api/routes.py` — 消息内容无 `max_length=2000` 校验。✅ **已修**: `MessageInput.content` 用 `Field(max_length=2000)`，`agent_run` 加二次校验返回 4001
- [x] **S2-06** `python-service/main.py` — 直接访问 `redis_client._client.ping()` 而非用公 API `is_available()`。✅ **已修**: 统一用 `is_available()`
- [x] **S2-07** `python-service/main.py` — 启动时 Redis/PG 不可用直接崩溃，无降级启动。✅ **已修**: try/except 包裹；仅双不可用才崩溃；支持 Redis-only / PG-only 降级模式

---

## 🟢 Low (4 条)

- [x] **S2-08** `python-service/app/agents/base.py` — `BaseAgent.name` 定义为类级注解而非 `@abstractmethod` property。✅ **已修**: 改为 `@property @abstractmethod` on `BaseAgent(ABC)`
- [x] **S2-09** `python-service/app/agents/base.py` + `routes.py` — `reply` 字段无 `max_length=1000` 约束。✅ **已修**: `AgentResult.__post_init__` 裁切 + `_truncate_reply` 双重保证
- [x] **S2-10** `python-service/app/agents/base.py` — `SessionContext` 的 `input` 与 message 内容重复。✅ 无需修: `input` 是消息文本的唯一载体，`message_type`/`image_url` 处理类型区分，无冗余
- [x] **S2-11** `python-service/main.py` — `/health` 端点只查 Redis 不查 PG/FE gRPC/LLM API。✅ **已修**: `/health` + `/agent/health` 均检查 Redis + PG；FE/LLM 占位 `"unchecked"` 由 Step 5/6 接入
