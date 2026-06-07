# Step 2：Python 骨架

> **上下文范围**：PRD 第 5（Agent 与 Tool 定义）、第 14 节（Python 层重构）、第 19 节（接口契约）
> **前置依赖**：Step 1（DB + Redis + 环境变量）
> **完成标准**：FastAPI `/agent/run` 和 `/agent/resume` 返回 mock 事件流，BaseAgent 接口定义完成，Observation 基础埋点就绪

---

## 2.1 目录结构

```
python-service/app/
├── main.py
├── config.py
├── orchestrator/
│   ├── router.py              # 意图分类(Flash LLM)
│   ├── session.py             # 会话上下文
│   └── front_agent.py
├── agents/
│   ├── base.py                # BaseAgent + AgentResult + SessionContext
│   ├── diagnosis.py
│   ├── photo.py
│   ├── workshop.py
│   ├── schedule.py
│   └── reflection.py
├── identity/
│   ├── registry.py            # Capability Registry
│   └── journal.py
├── tools/
│   ├── fe_tool.py
│   ├── rag_tool.py
│   ├── product_tool.py
│   └── profile_tool.py
├── observation/
│   ├── telemetry.py
│   └── escalation.py
├── prompts/
│   └── templates.py
├── engine/
│   └── llm.py
├── skin_analysis/
├── recommender/
├── knowledge/
└── api/
    └── routes.py
```

---

## 2.2 BaseAgent 接口定义

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class StatusEvent:
    seq: int
    source: str                        # "tool:fe_retrieve" / "agent:workshop"
    status: Literal["running", "done", "error"]
    label: str
    duration_ms: int = 0
    created_at: str = ""               # ISO8601

@dataclass
class InterruptRequest:
    type: str                          # "confirm_allergy" 等
    question: str
    options: list[str]
    timeout_s: int = 300
    created_at: str = ""               # ISO8601

@dataclass
class CardPayload:
    type: Literal["workshop_card", "skin_report_card", "schedule_card", "interrupt_card"]
    data: dict

@dataclass
class AgentResult:
    state: dict                        # 可 JSON 序列化的 agent 内部状态
    reply: str                         # 给用户的文本，最长 1000 字
    interrupt: InterruptRequest | None = None
    events: list[StatusEvent] = field(default_factory=list)
    card: CardPayload | None = None
    done: bool = True                  # False = agent 还需继续
    error: str | None = None           # 非 None 时 stage → error

@dataclass
class SessionContext:
    session_id: str
    user_id: int
    tenant_id: int
    platform: str                      # "web" | "wecom" | "douyin" | "xhs"
    input: str                         # 用户消息内容
    agent_state: dict                  # 从 SessionState 带入
    message_type: str = "text"         # "text" | "image"
    image_url: str | None = None

class BaseAgent:
    name: str
    async def run(self, ctx: SessionContext, input: str) -> AgentResult: ...
    async def resume(self, ctx: SessionContext, reply: str) -> AgentResult: ...
```

要求：
- `AgentResult.state` 必须可 JSON 序列化（供 Redis/PG 持久化）
- `run()` 和 `resume()` 都是 async，支持 `asyncio.wait_for` 超时控制
- `resume()` 只在 `stage = agent_interrupted` 时被调用

---

## 2.3 API 路由

### POST /agent/run

```json
// Request
{
  "session_id": "conv_abc123",
  "user_id": 42,
  "tenant_id": 1,
  "platform": "wecom",
  "message": {
    "type": "text",
    "content": "我是油皮，推荐个洗面奶",
    "image_url": null
  },
  "agent_state": {}
}

// Response
{
  "session_id": "conv_abc123",
  "events": [
    {"type": "status", "data": {...}},
    {"type": "reply",  "data": {"text": "收到~"}},
    {"type": "card",   "data": {...}},
    {"type": "done",   "data": {}}
  ],
  "new_agent_state": {},
  "interrupt": null,
  "error": null
}
```

### POST /agent/resume

```json
// Request
{
  "session_id": "conv_abc123",
  "user_id": 42,
  "tenant_id": 1,
  "interrupt_reply": "没有过敏",
  "agent_state": {}
}

// Response: 同 /agent/run
```

### GET /agent/health

返回 `{"status": "ok", "version": "0.3.0"}`

要求：
- 本 Step 返回 mock 数据即可，真实逻辑在后续 Step 实现
- mock 数据至少包含 `reply` + `done` 事件
- 错误时返回统一错误码格式

---

## 2.4 Capability Registry

```python
CAPABILITY_REGISTRY = {
    "workshop": {
        "name": "配药师",
        "capabilities": ["recommend_product", "build_routine", "check_conflicts"],
        "required_model": "pro",
        "interruptible": True,
        "timeout_s": 30,
        "priority": 10,
    },
    "diagnosis": {
        "name": "问卷师",
        "capabilities": ["skin_diagnosis", "collect_profile"],
        "required_model": "flash",
        "interruptible": False,
        "timeout_s": 600,
        "priority": 5,
    },
    "photo_analyst": {
        "name": "识肤师",
        "capabilities": ["analyze_photo", "visual_diagnosis"],
        "required_model": "vl",
        "interruptible": True,
        "timeout_s": 30,
        "priority": 8,
    },
    "copywriter": {
        "name": "日报官",
        "capabilities": ["generate_schedule", "push_notification"],
        "required_model": "flash",
        "interruptible": True,
        "timeout_s": 20,
        "priority": 3,
    },
}
```

---

## 2.5 Observation Telemetry 基础埋点

```python
# observation/telemetry.py
# 本 Step 实现基础框架，具体埋点在 Step 6 各 Agent 中补全

@dataclass
class TraceEvent:
    trace_id: str                      # "tr_" + uuid4_hex[:12]
    session_id: str
    agent: str
    events: list[dict] = field(default_factory=list)  # 逐步追加
    total_ms: int = 0
    user_feedback: str | None = None

class Telemetry:
    async def start_trace(self, session_id: str, agent: str) -> str: ...
    async def add_event(self, trace_id: str, event: dict) -> None: ...
    async def finish_trace(self, trace_id: str, total_ms: int) -> None: ...
    async def flush_to_db(self, trace_id: str) -> None: ...
```

Trace 数据结构：
```json
{
  "trace_id": "tr_abc123",
  "session_id": "conv_456",
  "agent": "workshop",
  "events": [
    {"tool": "fe_retrieve",    "duration_ms": 240, "success": true},
    {"tool": "product_search", "duration_ms": 180, "success": true},
    {"llm_call": "pro_match",  "duration_ms": 2100, "tokens": 4500},
    {"result": "workshop_card", "total_ms": 3500, "success": true}
  ],
  "user_feedback": "selected",
  "created_at": "2026-06-07T10:30:00Z"
}
```

---

## 2.6 验收标准

- [ ] `python-service/` 目录结构创建完整
- [ ] `BaseAgent` 抽象类定义完成，`AgentResult` / `SessionContext` dataclass 就位
- [ ] `CAPABILITY_REGISTRY` 注册 4 个 Agent 类型
- [ ] `POST /agent/run` 返回 mock AgentResult（含 reply + done 事件）
- [ ] `POST /agent/resume` 返回 mock AgentResult
- [ ] `GET /agent/health` 返回健康状态
- [ ] `Telemetry` 类可用，`start_trace` / `add_event` / `finish_trace` 写入 observation_traces 表
- [ ] 所有响应带统一错误码格式（code / message / data / trace_id）
