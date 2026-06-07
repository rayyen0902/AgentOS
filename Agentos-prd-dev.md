# AgentOS v0.3 — 全栈重构 PRD（开发版）

> **文档说明**：本文档在原始 PRD 基础上补全了接口契约、错误码规范、边界条件与异常流、依赖关系图，以及各模块的明确约束，达到可直接开发标准。新增内容以 `[补全]` 标记。

-----

## 目录

1. 项目背景与目标
1. 技术栈
1. 全异步架构
1. 状态机设计
1. Agent 与 Tool 定义
1. Agent 身份与能力注册中心
1. Memory OS 升级
1. Agent 自进化与运营闭环
1. RAG 知识检索体系
1. 消息投递通道
1. 租户自助注册
1. 平台渠道接入
1. 数据库变更
1. Python 层重构
1. Go 层重构
1. 前端重构
1. 实施路线
1. 验证清单
1. **[补全] 接口契约与错误码规范**
1. **[补全] 边界条件与异常流**
1. **[补全] 环境变量与配置清单**
1. **[补全] 阶段依赖关系图**

-----

## 1. 项目背景与目标

### 1.1 现状痛点

- `ProcessMessage` 单函数 ~400 行，所有逻辑耦合在一步
- 各能力（FE/RAG/推荐/识肤）if-else 堆砌，扩展困难
- 同步等待 LLM 响应，用户发消息后干等 3-5 秒
- 前端单文件（chat.html + chat.js ~1200行），无框架
- FE 记忆实际不可用（proto 版本错位）
- 无流式推送，配药师轮询 2 秒一次体验差
- 无租户自助注册，全靠人工后台开 tenant
- 无渠道平台接入（仅占位 webhook）

### 1.2 重构目标

- **全异步**：前台 Agent 秒级响应，后台 Agent 并行工作，结果 SSE 实时推送
- **Agent 架构**：Orchestrator 编排 + 子 Agent 委派 + Tool 调用
- **状态机驱动**：Agent 状态持久化（Redis + PG），中断→恢复
- **SSE 实时推送**：Tool/Agent 状态、中断事件、卡片结果实时可见
- **技术栈分层**：React → Go（路由/网关）→ Python（Agent层）→ FE（记忆）
- **租户自助注册**：品牌方在线入驻，审批开通
- **渠道接入**：企微/抖音/小红书官方接口对接
- **全量重写**：不兼容旧版，新代码库

### 1.3 [补全] 非功能性约束

|指标                   |目标值                                      |测量方式                   |
|---------------------|-----------------------------------------|-----------------------|
|前台 Agent 首次响应        |≤ 500ms（p95）                             |Observation Layer trace|
|子 Agent 总耗时          |≤ 5s（p95）                                |Observation Layer trace|
|SSE 事件到达延迟           |≤ 200ms                                  |前端打点                   |
|Redis SessionState 读写|≤ 10ms（p99）                              |服务监控                   |
|系统可用性                |≥ 99.5%                                  |月度统计                   |
|单 Agent 最大 token 消耗  |Pro ≤ 8000 tokens/次，Flash ≤ 2000 tokens/次|Observation Layer      |

-----

## 2. 技术栈

```
┌──────────────────────────────────────────────────────┐
│  React SPA (Vite + TypeScript)                        │
│  · SSE订阅 · 消息渲染 · 状态卡片 · PWA               │
└──────────┬───────────────────────────────────────────┘
           │ HTTP + SSE
┌──────────▼───────────────────────────────────────────┐
│  Go 路由层 (net/http)                                 │
│  · 鉴权 · 限流 · SessionState管理 · SSE中转          │
│  · 平台Webhook入口                                    │
└──────────┬───────────────────────────────────────────┘
           │ HTTP (本地)
┌──────────▼───────────────────────────────────────────┐
│  Python Agent 层 (FastAPI)                            │
│  · Orchestrator · 子Agent · Tool · LLM调用           │
└──────────┬───────────────────────────────────────────┘
           │ gRPC
┌──────────▼───────────────────────────────────────────┐
│  遗忘引擎 FE (knownot.cc:50052)                       │
└──────────────────────────────────────────────────────┘
```

|层     |做                                         |不做                    |
|------|------------------------------------------|----------------------|
|React |Web Demo：渲染 + SSE 订阅                      |不调 LLM、不写业务           |
|Go    |路由 + 鉴权 + SessionState + 平台回调 + Webhook 验证|不调 LLM、不写 Agent 逻辑    |
|Python|Agent 编排 + LLM + Tool + RAG               |不处理 HTTP 鉴权/限流、不感知平台差异|
|FE    |记忆读写 + 用户画像                               |不参与业务流程               |

### [补全] 版本锁定

|组件        |版本    |备注                 |
|----------|------|-------------------|
|Go        |1.22+ |泛型 + 标准 net/http   |
|Python    |3.11+ |asyncio 完善         |
|FastAPI   |0.111+|                   |
|React     |18.3+ |concurrent features|
|Vite      |5.x   |                   |
|TypeScript|5.x   |                   |
|Redis     |7.x   |TTL + Stream 支持    |
|PostgreSQL|15+   |pgvector 扩展        |
|pgvector  |0.7+  |ivfflat 索引         |

-----

## 3. 全异步架构

### 3.1 核心原则

> **前台 Agent 永远在平台要求时间内响应用户消息。子 Agent 结果通过平台原生 API 主动推送。**

主流平台（企微/抖音/小红书）的消息模型都是「接收消息→被动回复→主动推送」。同步等待 LLM 会超时，必须异步。

### 3.2 异步模型

```
用户消息 (平台 Webhook)
    │
    ▼
Go: 验签 → 归一化 → 转发 Python
    │
    ▼
前台 Agent (Flash LLM, < 平台超时)
    │
    ├─→ 立即被动回复 "收到，配药师正在为您挑选..."
    ├─→ 异步委派子 Agent 后台运行
    │
    ▼ (异步 goroutine/asyncio.create_task)
子 Agent 后台执行:
    ├─ fe_retrieve → fe_ingest
    ├─ product_catalog → Pro LLM 匹配
    └─ 完成 → 写结果到 SessionState
    │
    ▼
Go: SessionState → 事件队列 → 平台主动推送
    企微: POST /cgi-bin/message/send
    抖音: POST /im/send_msg/
    Web:  SSE push (调试用)
```

### 3.3 消息时序（以企微为例）

```
T+0ms     企微服务器 POST 用户消息到 Webhook
T+200ms   Go 验签 → 归一化 → 转发 Python
T+400ms   前台 Agent 回复 → Go 被动回复 200 OK "好的，正在处理..."
T+800ms   子 Agent 启动（后台 goroutine）
T+1.2s    子 Agent: FE 检索完成
T+3.0s    子 Agent: 产品匹配完成
T+3.1s    Go 主动调用企微 API 推送结果卡片 → 用户看到推荐
```

### 3.4 各渠道投递方式

|渠道      |被动回复（同步）          |主动推送（异步）                    |中断反调                  |
|--------|------------------|----------------------------|----------------------|
|企微      |Webhook 200 响应 XML|POST `/cgi-bin/message/send`|主动推送文本+按钮卡片           |
|抖音      |Webhook 200 响应    |POST `/im/send_msg/`        |主动推送文本+选项             |
|小红书     |Webhook 200 响应    |私信 API                      |主动推送文本+选项             |
|Web Demo|HTTP 200          |SSE (调试) / 轮询(降级)           |SSE push InterruptCard|

### [补全] 3.5 后台任务超时与取消策略

|Agent   |超时时间        |超时后行为              |
|--------|------------|-------------------|
|前台 Agent|3s          |返回兜底回复”稍后再试” + 记录告警|
|配药师     |30s         |主动推送”分析超时，已记录，稍后重试”|
|识肤师     |30s         |同上                 |
|问卷师     |600s（单步 30s）|单步超时 → 重发当前问题      |
|日报官     |20s         |跳过本次推送，下次触发时重试     |

超时机制：Python 侧用 `asyncio.wait_for`；Go 侧用 `context.WithTimeout`。

-----

## 4. 状态机设计

### 4.1 SessionState

```json
{
  "session_id": "conv_123",
  "stage": "agent_running",
  "current_agent": "workshop",
  "agent_state": { "phase": "matching", "step": 2 },
  "interrupt": null,
  "status_stream": [
    {"seq":1, "source":"tool:fe_retrieve", "status":"done", "label":"肤质档案已加载"},
    {"seq":2, "source":"agent:workshop", "status":"running", "label":"正在匹配产品"}
  ]
}
```

### [补全] 4.1.1 SessionState 字段完整定义

|字段             |类型                     |必填|说明                                                      |
|---------------|-----------------------|--|--------------------------------------------------------|
|`session_id`   |string                 |是 |格式：`conv_{uuid4_hex[:16]}`                              |
|`stage`        |enum                   |是 |`idle` / `agent_running` / `agent_interrupted` / `error`|
|`current_agent`|string | null          |否 |运行中的 Agent 名，idle 时为 null                               |
|`agent_state`  |object                 |否 |Agent 自定义状态，由 Agent 负责序列化                               |
|`interrupt`    |InterruptRequest | null|否 |见下方 InterruptRequest 定义                                 |
|`status_stream`|StatusEvent[]          |是 |初始为 `[]`                                                |
|`user_id`      |bigint                 |是 |                                                        |
|`tenant_id`    |bigint                 |是 |                                                        |
|`platform`     |string                 |是 |`web` / `wecom` / `douyin` / `xhs`                      |
|`created_at`   |ISO8601                |是 |                                                        |
|`updated_at`   |ISO8601                |是 |每次写入更新                                                  |
|`ttl_seconds`  |int                    |是 |默认 1800（30min）                                          |

**InterruptRequest 结构：**

```json
{
  "type": "confirm_allergy",
  "question": "您对以下成分是否有过敏史？烟酰胺、水杨酸",
  "options": ["没有过敏", "烟酰胺过敏", "水杨酸过敏", "都过敏"],
  "timeout_s": 300,
  "created_at": "2026-06-07T10:00:00Z"
}
```

**StatusEvent 结构：**

```json
{
  "seq": 1,
  "source": "tool:fe_retrieve",
  "status": "running | done | error",
  "label": "肤质档案已加载",
  "duration_ms": 240,
  "created_at": "2026-06-07T10:00:00Z"
}
```

### 4.2 状态流转

```
idle
  │ 用户消息
  ▼
agent_running
  │ 子Agent需要确认 → interrupt 写入
  ▼
agent_interrupted
  │ 用户回复
  ▼
agent_running (继续)
  │ 完成 → 清理 agent_state
  ▼
idle
```

### [补全] 4.2.1 异常状态流转

```
agent_running
  │ 超时 / Tool 三次失败
  ▼
error
  │ 错误信息写入 SessionState.error_info
  │ 推送用户兜底回复
  ▼
idle（自动恢复，可接受下条消息）

agent_interrupted
  │ interrupt.timeout_s 到期且用户未回复
  ▼
agent_running（使用默认选项继续，默认选项 = options[0]）
  │ 记录 interrupt_timed_out=true 到 agent_audit_log
```

### 4.3 持久化

- **Redis**：热状态（TTL 30min），快速读写
- **PostgreSQL** `session_states`：冷存储 + 审计
- Agent 内部 state 由 Agent 自己 marshal/unmarshal

### [补全] 4.3.1 Redis Key 规范

```
session:{session_id}            → SessionState JSON（TTL 1800s）
sse_channel:{session_id}        → Redis Stream（SSE 事件队列，TTL 3600s）
agent_lock:{session_id}         → 分布式锁（TTL = agent 超时时间，防并发）
access_token:wecom:{corp_id}    → 企微 AccessToken（TTL = expires_in - 60s）
embed_cache:{sha256(text)}      → Embedding 向量（TTL 3600s）
```

-----

## 5. Agent 与 Tool 定义

### 5.1 Tool（无状态函数）

|Tool           |功能       |输入                      |输出     |
|---------------|---------|------------------------|-------|
|`fe_retrieve`  |读记忆上下文   |query                   |格式化文本  |
|`fe_ingest`    |写记忆      |text + role + session_id|msg_id |
|`rag_search`   |知识检索     |query                   |知识条目列表 |
|`rag_conflict` |成分冲突检测   |product/ingredient      |冲突规则   |
|`product_crud` |产品录入/查询  |action + data           |产品列表   |
|`profile_query`|用户肤质/档案查询|user_id                 |肤质+在用产品|

### [补全] 5.1.1 Tool 完整接口规范

```python
# fe_retrieve
class FERetrieveInput(BaseModel):
    query: str                          # 检索关键词，最长 200 字
    layer: Literal["semantic", "episodic", "preference", "all"] = "all"
    n: int = Field(default=5, ge=1, le=20)   # 返回条数
    user_id: int
    namespace: str                      # 格式: "tenant:{tenant_id}:agent:{agent_type}"

class FERetrieveOutput(BaseModel):
    content: str                        # 格式化后可直接注入 prompt 的文本
    raw_items: list[MemoryItem]         # 原始条目（调试用）
    retrieved_count: int

# fe_ingest
class FEIngestInput(BaseModel):
    text: str                           # 最长 4000 字
    role: Literal["user", "assistant"]
    session_id: str
    user_id: int
    namespace: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)  # 重要度评分

class FEIngestOutput(BaseModel):
    msg_id: str
    success: bool

# rag_search
class RAGSearchInput(BaseModel):
    query: str
    tenant_id: int
    top_k: int = Field(default=5, ge=1, le=20)
    search_type: Literal["hybrid", "semantic", "keyword"] = "hybrid"

class RAGSearchOutput(BaseModel):
    items: list[KnowledgeItem]
    total: int

# rag_conflict
class RAGConflictInput(BaseModel):
    ingredients: list[str]              # 成分名列表
    user_id: int                        # 用于查个人过敏史
    check_types: list[str] = ["ingredient_conflict", "skin_sensitivity", "dosage_excess"]

class RAGConflictOutput(BaseModel):
    conflicts: list[ConflictItem]       # 空列表 = 无冲突
    has_urgent: bool                    # 有 high severity 冲突时为 true

# product_crud
class ProductCRUDInput(BaseModel):
    action: Literal["create", "read", "update", "list", "search"]
    tenant_id: int
    data: dict = {}                     # action=create/update 时填
    product_id: int | None = None      # action=read/update 时填
    query: str | None = None           # action=search 时填

# profile_query
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

### [补全] 5.1.2 Tool 失败重试策略

|Tool           |最大重试|重试间隔 |失败兜底                         |
|---------------|----|-----|-----------------------------|
|`fe_retrieve`  |2次  |500ms|返回空上下文，Agent 继续无记忆模式运行       |
|`fe_ingest`    |3次  |1s   |记录失败日志，不阻断主流程                |
|`rag_search`   |2次  |500ms|返回空结果，Agent 告知用户”暂时无法查询知识库”  |
|`rag_conflict` |2次  |500ms|返回 has_urgent=false（降级，不阻断推荐）|
|`product_crud` |1次  |立即   |返回错误，上抛 Agent 处理             |
|`profile_query`|2次  |500ms|返回空 profile，Agent 改走问卷路径     |

### 5.2 Agent（多轮状态机，可中断）

|Agent  |功能          |模型   |可中断    |
|-------|------------|-----|-------|
|前台Agent|意图路由 + 即时回复 |Flash|—      |
|问卷师    |7步肤质问诊 → 报告 |Flash|否(轮内)  |
|识肤师    |照片 → 多维度分析  |VL   |可追问确认  |
|配药师    |肤质+需求 → 产品匹配|Pro  |可反调确认成分|
|日报官    |早晚日报生成+推送   |Flash|可确认调整  |

### 5.3 意图路由

```
用户消息 → 前台Agent(Flash) 分类 →
  ├─ "推荐/买什么/选哪个"            → 配药师 Agent
  ├─ "拍照/看皮肤/帮我看看"           → 识肤师 Agent
  ├─ "肤质检测/做问卷/测一测"         → 问卷师 Agent
  ├─ "日报/今天怎么护肤/明天"         → 日报官 Agent
  ├─ "录入/添加产品/我在用"           → product_crud Tool
  ├─ "什么是/成分/功效/适不适合"      → rag_search Tool
  └─ "聊天/问候/问进度"               → 前台Agent直出
```

### [补全] 5.3.1 意图路由 Prompt 规范

前台 Agent 使用以下结构输出意图（JSON Only 模式）：

```json
{
  "intent": "recommend_product | skin_diagnosis | photo_analysis | daily_schedule | product_add | knowledge_query | chat",
  "confidence": 0.92,
  "sub_intent": "routine_build",
  "extracted_entities": {
    "skin_concern": "控油",
    "product_category": "洗面奶"
  },
  "immediate_reply": "收到，配药师正在为您挑选~"
}
```

若 confidence < 0.6，前台 Agent 直接对话澄清，不委派子 Agent。

### 5.4 接口定义

```python
class AgentResult:
    state: AgentState               # 当前状态(可序列化)
    reply: str                      # 给用户的文本
    interrupt: dict | None          # 中断请求
    events: list[StatusEvent]       # 状态事件流
    card: dict | None               # 卡片数据

class BaseAgent:
    name: str
    async def run(self, ctx: SessionContext, input: str) -> AgentResult: ...
    async def resume(self, ctx: SessionContext, reply: str) -> AgentResult: ...
```

### [补全] 5.4.1 AgentResult 完整字段

```python
@dataclass
class AgentResult:
    state: dict                         # 可 JSON 序列化的 agent 内部状态
    reply: str                          # 给用户的文本，最长 1000 字
    interrupt: InterruptRequest | None  # 非 None 时 stage → agent_interrupted
    events: list[StatusEvent]           # SSE status 事件列表
    card: CardPayload | None            # 非 None 时通过 SSE card 事件推送
    done: bool = True                   # False = agent 还需继续（问卷中间步骤）
    error: str | None = None            # 非 None 时 stage → error

@dataclass
class CardPayload:
    type: Literal["workshop_card", "skin_report_card", "schedule_card", "interrupt_card"]
    data: dict                          # 卡片具体内容，见各 Agent 卡片数据规范
```

### [补全] 5.4.2 各 Agent 卡片数据规范

**workshop_card（配药师推荐）：**

```json
{
  "products": [
    {
      "id": 123,
      "name": "产品名",
      "brand": "品牌",
      "category": "洗面奶",
      "price": 199,
      "reason": "适合油皮，控油不紧绷",
      "key_ingredients": ["水杨酸", "烟酰胺"],
      "image_url": "https://..."
    }
  ],
  "conflicts": [],
  "routine_tip": "早晚均可使用，避免与高浓度VC同步"
}
```

**skin_report_card（肤质报告）：**

```json
{
  "skin_type": "混合偏油",
  "dimensions": {
    "oil_level": 4,
    "sensitivity": 2,
    "hydration": 3,
    "pigmentation": 2
  },
  "concerns": ["毛孔粗大", "T区出油"],
  "recommendations": ["控油洁面", "轻薄保湿"],
  "generated_at": "2026-06-07T10:00:00Z"
}
```

**interrupt_card（中断确认）：**

```json
{
  "question": "您对以下成分是否有过敏史？",
  "options": ["没有过敏", "烟酰胺过敏", "水杨酸过敏"],
  "timeout_s": 300
}
```

-----

## 6. Agent 身份与能力注册中心

### 6.1 Agent Identity（身份层）

```json
{
  "agent_id": "workshop_tenant_1",
  "agent_type": "workshop",
  "persona": "资深护肤配药师",
  "display_name": "肤小护·配药喵",
  "tenant_id": 1,
  "created_at": "2026-06-01T00:00:00Z",
  "memory_namespace": "tenant:1:agent:workshop",
  "capabilities": ["recommend_product", "build_routine", "check_conflicts"],
  "tone": "专业温暖",
  "custom_prompt": null,
  "version": "1.0.0"
}
```

### 6.2 Agent Capability Registry（能力注册中心）

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

### [补全] 6.2.1 并发控制规范

- 同一 session_id 同一时刻只允许一个 Agent 运行（通过 `agent_lock:{session_id}` Redis 锁保证）
- 新消息到达时若 stage = `agent_running`：前台 Agent 回复”正在处理上一条，稍等~”，不启动新 Agent
- 新消息到达时若 stage = `agent_interrupted`：视为中断回复，路由至 `agent.resume()`

### [补全] 6.2.2 Agent Identity 数据库表

```sql
CREATE TABLE agent_identities (
    id BIGSERIAL PRIMARY KEY,
    agent_id VARCHAR(128) UNIQUE NOT NULL,   -- "{agent_type}_tenant_{tenant_id}"
    agent_type VARCHAR(64) NOT NULL,
    tenant_id BIGINT REFERENCES tenants(id),
    persona TEXT,
    display_name VARCHAR(64),
    tone VARCHAR(32),
    custom_prompt TEXT,
    memory_namespace VARCHAR(256),
    capabilities JSONB DEFAULT '[]',
    version VARCHAR(16) DEFAULT '1.0.0',
    status VARCHAR(16) DEFAULT 'active',     -- active | deprecated
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

-----

## 7. Memory OS 升级

### 7.1 三层记忆结构

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

### 7.2 FE 升级路径

|版本      |内容                                                     |
|--------|-------------------------------------------------------|
|v0.5（当前）|Kin Profile 扁平 + 时序消息流                                 |
|v1.0（目标）|Episodic + Semantic + Preference + Memory Consolidation|

### 7.3 Agent 分层调用策略

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

### [补全] 7.4 Memory Consolidation 规则

- 触发时机：每次对话结束后，由 Reflection Agent 异步触发
- 窗口：7 天内出现 ≥ 3 次的相同语义事实 → 从 Episodic 提升至 Semantic
- 写入：通过 `fe_ingest` Tool，`importance = 0.8`
- 去重：相同 namespace + 相似度 > 0.95 的 Semantic 条目合并（FE 侧负责）

-----

## 8. Agent 自进化与运营闭环

### 8.1 Reflection Agent

```python
class ReflectionAgent(BaseAgent):
    async def reflect(self, session: SessionContext, result: AgentResult) -> Reflection:
        analysis = await self.llm.analyze(
            user_message=session.input,
            agent_response=result.reply,
            tools_called=result.tool_calls,
            outcome=session.outcome,
        )
        return Reflection(
            satisfaction=analysis.satisfaction,
            lesson=analysis.lesson,
            rule_candidate=analysis.new_rule,
            should_escalate=analysis.risk_level == "high",
        )
```

### [补全] 8.1.1 Reflection 触发条件

|条件                       |是否触发 Reflection     |
|-------------------------|--------------------|
|配药师 workshop_card 推送完成   |是                   |
|识肤师 skin_report_card 推送完成|是                   |
|问卷师 7 步完成                |是                   |
|前台 Agent 直出（无子 Agent）    |否                   |
|Agent 超时/报错              |否（记录 Observation 即可）|

Reflection 为异步任务，使用 `asyncio.create_task`，不阻塞主流程。Reflection 失败不影响用户体验，只记录日志。

### 8.2 Agent Journal（成长日志）

每周日 00:00 UTC 定时生成，内容包括：

- 本周服务用户数 / 推荐次数
- 采纳率（选购/下单）
- 高频需求 Top3
- 新发现（Reflection 汇总）
- 策略调整建议

### 8.3 Observation Layer（遥测层）

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

### [补全] 8.3.1 告警规则

|指标         |阈值          |告警级别    |动作                   |
|-----------|------------|--------|---------------------|
|任意 Tool 失败率|> 10% / 5min|WARNING |站内通知                 |
|Agent 整体失败率|> 5% / 5min |ERROR   |站内 + 短信              |
|LLM p95 延迟 |> 8s        |WARNING |站内通知                 |
|FE gRPC 错误率|> 20% / 5min|CRITICAL|站内 + 短信 + 自动降级（无记忆模式）|

### 8.4 Agent 评价体系

|维度        |定义        |数据来源                  |
|----------|----------|----------------------|
|Accuracy  |推荐产品是否匹配肤质|Reflection Agent + 选购率|
|Conversion|推荐→选购/下单转化|选购回调 + 订单数据           |
|Retention |用户 7 日内回访率|会话日志                  |
|Trust     |采纳率 / 追问率 |Reflection Agent 评估   |

### 8.5 Human Escalation（人工升级）

```python
ESCALATION_RULES = [
    {"condition": "过敏反应描述（红肿/刺痛/起疹）", "level": "urgent",   "action": "转人工 + 站内告警"},
    {"condition": "烂脸/严重不良反应",             "level": "emergency", "action": "转人工 + 电话/短信通知"},
    {"condition": "投诉/退款/法律威胁",             "level": "high",     "action": "转人工客服"},
    {"condition": "医疗建议请求（处方药/皮肤病）",   "level": "high",     "action": "拒答 + 建议就医"},
    {"condition": "成分过敏确认",                   "level": "medium",   "action": "中断 + 人工确认"},
]
```

### [补全] 8.5.1 Escalation 执行细节

- 检测时机：前台 Agent 意图分类完成后，子 Agent 启动前
- 检测方式：规则匹配（关键词 + 正则）+ Flash LLM 二次确认（高敏感场景）
- 转人工后：SessionState.stage → `escalated`，不再接受 Agent 处理，只记录消息
- 恢复：管理员在后台手动将 stage 重置为 `idle`

-----

## 9. RAG 知识检索体系

### 9.1 现有基础（保留升级）

|组件       |现状                            |v2.0 变更        |
|---------|------------------------------|---------------|
|向量库      |PostgreSQL + pgvector         |增加 ivfflat 索引优化|
|Embedding|Qwen text-embedding-v4 (1024d)|增加 Redis 缓存层   |
|成分百科     |`knowledge.ingredients`       |保留             |
|功效标签     |`knowledge.functions`         |保留             |
|原料目录     |`knowledge.iecic`             |保留             |
|成分别名     |`knowledge.ingredient_aliases`|保留，持续扩充        |
|冲突规则     |`knowledge.conflict_rules`    |增加产品-产品互斥规则    |

### 9.2 新增能力

#### 9.2.1 产品语义搜索

```sql
ALTER TABLE products ADD COLUMN embedding vector(1024);
CREATE INDEX idx_products_embedding ON products USING ivfflat (embedding vector_cosine_ops);
```

#### 9.2.2 混合检索（Hybrid Search）

```python
def hybrid_search(query: str, tenant_id: int, top_k: int = 5) -> list[Product]:
    vec = embed_single(query)
    semantic = pgvector_search(vec, tenant_id, limit=top_k * 2)
    filters = extract_filters(query)
    keyword = sql_filter_search(filters, tenant_id, limit=top_k)
    return rrf_merge(semantic, keyword, top_k)
```

### [补全] 9.2.2.1 RRF 融合参数

```python
def rrf_merge(semantic: list, keyword: list, top_k: int, k: int = 60) -> list:
    """Reciprocal Rank Fusion"""
    scores = {}
    for rank, item in enumerate(semantic):
        scores[item.id] = scores.get(item.id, 0) + 1 / (k + rank + 1)
    for rank, item in enumerate(keyword):
        scores[item.id] = scores.get(item.id, 0) + 1 / (k + rank + 1)
    sorted_ids = sorted(scores, key=scores.get, reverse=True)
    return [get_product(id) for id in sorted_ids[:top_k]]
```

#### 9.2.3 冲突检测增强

```sql
CREATE TABLE knowledge.product_conflicts (
    id SERIAL PRIMARY KEY,
    product_a_id BIGINT REFERENCES products(id),
    product_b_id BIGINT REFERENCES products(id),
    conflict_type VARCHAR(32),
    severity VARCHAR(8),
    description TEXT,
    suggestion TEXT
);
```

-----

## 10. 消息投递通道

### [补全] 10.1 SSE 事件类型完整规范

|event 名    |触发时机           |data 格式                                                                 |
|-----------|---------------|------------------------------------------------------------------------|
|`status`   |Tool/Agent 状态变化|`{"seq":1,"source":"tool:fe_retrieve","status":"running","label":"..."}`|
|`reply`    |文本回复就绪         |`{"text":"...", "from":"front_agent"}`                                  |
|`interrupt`|子 Agent 需要确认   |InterruptRequest JSON                                                   |
|`card`     |卡片数据就绪         |CardPayload JSON                                                        |
|`done`     |本轮全部完成         |`{"session_id":"...","total_ms":3500}`                                  |
|`error`    |Agent 报错       |`{"code":"AGENT_TIMEOUT","message":"..."}`                              |
|`heartbeat`|每 30s 保活       |`{}`                                                                    |

所有事件都带 `session_id` 字段，前端按 session_id 路由。

### 10.2 企微投递（略，见原 PRD）

### 10.3 抖音投递（略，见原 PRD）

### 10.4 Web Demo 投递（略，见原 PRD）

-----

## 11. 租户自助注册

### 11.1 注册流程（见原 PRD）

### [补全] 11.2 验证码规则

- 验证码：6 位纯数字
- 有效期：10 分钟
- 同一号码频率限制：1 次 / 60 秒，5 次 / 1 小时（Go 层 Redis 限流）
- 验证码使用后立即标记 `used=true`
- 注册后 24 小时内未审批 → 自动发邮件提醒管理员

### [补全] 11.3 API Key 规范

- 格式：`mimi_live_{base62(32bytes)}`（测试环境：`mimi_test_...`）
- 生成时机：管理员审批通过时自动生成
- 存储：SHA-256 哈希后存库，明文只在生成时返回一次
- 权限：API Key 绑定 tenant_id，所有请求校验归属

-----

## 12. 平台渠道接入（见原 PRD）

### [补全] 12.1 Webhook 安全规范

|渠道 |验签方式                                              |Go 实现要点             |
|---|--------------------------------------------------|--------------------|
|企微 |SHA1(token + timestamp + nonce + echostr)         |使用 `wxbizmsgcrypt` 库|
|抖音 |HMAC-SHA256(app_secret + timestamp + nonce + body)|标准 HMAC             |
|小红书|RSA 签名（官方 SDK）                                    |按官方文档实现             |

所有 Webhook 验签失败 → 返回 403，记录 `tenant_id` + IP 到 security_log，连续 10 次失败 → 触发告警。

-----

## 13. 数据库变更

### 13.1 新增表

```sql
-- Agent 会话状态
CREATE TABLE session_states (
    session_id   VARCHAR(64) PRIMARY KEY,
    user_id      BIGINT NOT NULL,
    tenant_id    BIGINT NOT NULL,
    platform     VARCHAR(16) NOT NULL DEFAULT 'web',
    stage        VARCHAR(32) DEFAULT 'idle',
    current_agent VARCHAR(64),
    agent_state  JSONB DEFAULT '{}',
    interrupt    JSONB,
    status_stream JSONB DEFAULT '[]',
    error_info   JSONB,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_session_states_user ON session_states(user_id);
CREATE INDEX idx_session_states_updated ON session_states(updated_at);

-- Agent 审计日志
CREATE TABLE agent_audit_log (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64),
    agent_name VARCHAR(64),
    event_type VARCHAR(32),
    event_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_log_session ON agent_audit_log(session_id);
CREATE INDEX idx_audit_log_created ON agent_audit_log(created_at);

-- Agent 身份
CREATE TABLE agent_identities (
    id BIGSERIAL PRIMARY KEY,
    agent_id VARCHAR(128) UNIQUE NOT NULL,
    agent_type VARCHAR(64) NOT NULL,
    tenant_id BIGINT REFERENCES tenants(id),
    persona TEXT,
    display_name VARCHAR(64),
    tone VARCHAR(32),
    custom_prompt TEXT,
    memory_namespace VARCHAR(256),
    capabilities JSONB DEFAULT '[]',
    version VARCHAR(16) DEFAULT '1.0.0',
    status VARCHAR(16) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 平台接入配置
CREATE TABLE tenant_platforms (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT REFERENCES tenants(id),
    platform VARCHAR(16),
    app_id VARCHAR(128),
    app_secret_hash VARCHAR(256),   -- SHA-256，明文不入库
    app_secret_encrypted TEXT,      -- AES-256-GCM 加密存储
    token VARCHAR(128),
    encoding_aes_key VARCHAR(256),
    webhook_url VARCHAR(512),
    status VARCHAR(16) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 注册验证码
CREATE TABLE verify_codes (
    id BIGSERIAL PRIMARY KEY,
    target VARCHAR(255),
    code VARCHAR(8),
    type VARCHAR(16),
    expires_at TIMESTAMPTZ,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_verify_codes_target ON verify_codes(target, used);

-- Observation 遥测
CREATE TABLE observation_traces (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(64) UNIQUE NOT NULL,
    session_id VARCHAR(64),
    tenant_id BIGINT,
    agent VARCHAR(64),
    events JSONB DEFAULT '[]',
    total_ms INT,
    user_feedback VARCHAR(32),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_traces_session ON observation_traces(session_id);
CREATE INDEX idx_traces_created ON observation_traces(created_at);
```

### 13.2 现有表变更

```sql
ALTER TABLE tenants ADD COLUMN email VARCHAR(255);
ALTER TABLE tenants ADD COLUMN phone VARCHAR(32);
ALTER TABLE tenants ADD COLUMN password_hash VARCHAR(255);
ALTER TABLE tenants ADD COLUMN status VARCHAR(16) DEFAULT 'active';
-- status: pending | active | suspended | rejected

ALTER TABLE products ADD COLUMN embedding vector(1024);
CREATE INDEX idx_products_embedding ON products USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE TABLE knowledge.product_conflicts (
    id SERIAL PRIMARY KEY,
    product_a_id BIGINT REFERENCES products(id),
    product_b_id BIGINT REFERENCES products(id),
    conflict_type VARCHAR(32),
    severity VARCHAR(8),
    description TEXT,
    suggestion TEXT
);
```

### [补全] 13.3 Migration 执行顺序

```
Step 1: ALTER TABLE tenants (无依赖)
Step 2: CREATE TABLE verify_codes (无依赖)
Step 3: CREATE TABLE agent_identities (依赖 tenants)
Step 4: CREATE TABLE tenant_platforms (依赖 tenants)
Step 5: CREATE TABLE session_states (无外键，可独立)
Step 6: CREATE TABLE agent_audit_log (无外键，可独立)
Step 7: CREATE TABLE observation_traces (无外键，可独立)
Step 8: ALTER TABLE products ADD COLUMN embedding (需先有 pgvector 扩展)
Step 9: CREATE INDEX idx_products_embedding (在 Step 8 后，可后台 CONCURRENTLY 创建)
Step 10: CREATE TABLE knowledge.product_conflicts (依赖 products)
```

### 13.4 保留不变

`skin_profiles`, `products`（主体）, `user_products`, `schedules`, `conversations`, `messages`, `billing_records`, `facts`

-----

## 14. Python 层重构

### 14.1 目录结构

```
python-service/app/
├── main.py
├── config.py
├── orchestrator/
│   ├── router.py              # 意图分类(Flash LLM)
│   ├── session.py             # 会话上下文
│   └── front_agent.py
├── agents/
│   ├── base.py
│   ├── diagnosis.py
│   ├── photo.py
│   ├── workshop.py
│   ├── schedule.py
│   └── reflection.py
├── identity/
│   ├── registry.py
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

### 14.2 API 路由

|方法  |路径             |功能             |
|----|---------------|---------------|
|POST|`/agent/run`   |执行 Agent（Go 转发）|
|POST|`/agent/resume`|恢复 Agent       |
|GET |`/agent/health`|健康检查           |

### [补全] 14.2.1 Python API 请求/响应规范

**POST /agent/run**

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
  "agent_state": {}            // 从 SessionState 带入，首次为 {}
}

// Response（流式 NDJSON 或同步 JSON，Go 侧根据 SSE 需要选择）
{
  "session_id": "conv_abc123",
  "events": [
    {"type": "status", "data": {...}},
    {"type": "reply",  "data": {"text": "收到~"}},
    {"type": "card",   "data": {...}},
    {"type": "done",   "data": {}}
  ],
  "new_agent_state": {...},
  "interrupt": null,
  "error": null
}
```

**POST /agent/resume**

```json
// Request
{
  "session_id": "conv_abc123",
  "user_id": 42,
  "tenant_id": 1,
  "interrupt_reply": "没有过敏",
  "agent_state": {...}        // 中断前的 agent_state
}

// Response: 同 /agent/run
```

-----

## 15. Go 层重构

### 15.1 路由表（见原 PRD）

### [补全] 15.2 Go 通用响应结构

```go
// 所有 API 统一响应格式
type APIResponse struct {
    Code    int         `json:"code"`    // 0=成功，非0=错误
    Message string      `json:"message"` // 错误描述，成功时为 "ok"
    Data    interface{} `json:"data"`    // 业务数据
    TraceID string      `json:"trace_id"`
}

// 成功
{"code":0,"message":"ok","data":{...},"trace_id":"tr_xxx"}

// 失败
{"code":4001,"message":"验证码不正确或已过期","data":null,"trace_id":"tr_xxx"}
```

### [补全] 15.3 中间件规范

|中间件      |作用                        |配置                                                |
|---------|--------------------------|--------------------------------------------------|
|RequestID|注入 trace_id               |每请求生成 UUID                                        |
|Auth     |JWT 验证（B端）/ API Key 验证（平台）|白名单：`/health`、`/api/v1/auth/*`、`/api/v1/webhook/*`|
|RateLimit|接口限流                      |全局 1000 req/min，单用户 60 msg/min                    |
|Recovery |panic 恢复                  |返回 500，记录堆栈                                       |
|Logger   |结构化日志                     |JSON 格式，含 trace_id / user_id / duration_ms        |

### [补全] 15.4 Go → Python 通信规范

- 协议：HTTP POST（本地回环，非 gRPC，降低复杂度）
- 超时：`context.WithTimeout(30s)`（与 Agent 最大超时对齐）
- 重试：不重试（Python 侧幂等性由 session_id 保证）
- 错误处理：Python 返回非 200 → Go 推送 SSE error 事件 → 前端展示兜底提示

-----

## 16. 前端重构

### 16.1 技术选型

- React 18 + TypeScript + Vite
- SSE：`EventSource`（内置重连）
- 状态管理：Zustand
- 嵌入模式：iframe + postMessage

### [补全] 16.2 SSE 断线重连策略

```typescript
const useSSE = (sessionId: string) => {
  useEffect(() => {
    let retryCount = 0;
    const maxRetry = 10;
    const connect = () => {
      const es = new EventSource(`/api/v1/chat/stream?session_id=${sessionId}`);
      es.addEventListener('heartbeat', () => { retryCount = 0; });
      es.onerror = () => {
        es.close();
        if (retryCount < maxRetry) {
          const delay = Math.min(1000 * 2 ** retryCount, 30000); // 指数退避，最长30s
          setTimeout(connect, delay);
          retryCount++;
        }
      };
    };
    connect();
  }, [sessionId]);
};
```

### [补全] 16.3 状态管理 Zustand Store 设计

```typescript
interface ChatStore {
  messages: Message[];
  statusStream: StatusEvent[];
  interrupt: InterruptRequest | null;
  currentCard: CardPayload | null;
  isProcessing: boolean;
  sseConnected: boolean;

  // actions
  appendMessage: (msg: Message) => void;
  appendStatus: (event: StatusEvent) => void;
  setInterrupt: (req: InterruptRequest | null) => void;
  setCard: (card: CardPayload | null) => void;
  finishProcessing: () => void;
  replyInterrupt: (option: string) => Promise<void>;
}
```

-----

## 17. 实施路线（见原 PRD）

### [补全] 17.1 各阶段验收标准

**阶段一完成标准（骨架搭建）：**

- Go SSE 接口可连接，心跳正常
- Python `/agent/run` 返回 mock 事件流
- React 正确渲染 SSE 事件
- Redis SessionState 读写正常
- FE proto 可调用 `GenerateKin`
- DB migration 全部执行成功

**阶段二完成标准（能力迁移）：**

- 发一条消息 → 500ms 内收到前台 Agent 回复
- 配药师推荐 → 3s 内收到 workshop_card
- 中断→用户回复→恢复正常
- 问卷师 7 步完成 → skin_report_card 渲染
- 识肤师上传图片 → 返回分析结果
- `hybrid_search` 返回语义相关产品

**阶段三完成标准（平台+运营）：**

- 企微发消息 → 3s 内收到 AI 回复
- 品牌方注册 → 审批通过 → 嵌入 widget 可用
- Knowledge Pipeline 人工审核界面可用
- Human Escalation 触发 → 消息记录正确

**阶段四完成标准（前端+上线）：**

- 所有 SSE 卡片组件渲染正常
- Agent 评价看板四维指标可查
- PWA 安装可用
- 旧版切换开关关闭后系统正常

-----

## 18. 验证清单（见原 PRD，略）

-----

## 19. [补全] 接口契约与错误码规范

### 19.1 统一错误码

|错误码 |含义                                      |HTTP 状态码|
|----|----------------------------------------|--------|
|0   |成功                                      |200     |
|4001|参数校验失败                                  |400     |
|4002|验证码错误/过期                                |400     |
|4003|手机号/邮箱已注册                               |400     |
|4011|未登录/Token 无效                            |401     |
|4012|API Key 无效                              |401     |
|4031|无权限（租户间隔离）                              |403     |
|4032|租户状态非 active（pending/suspended/rejected）|403     |
|4041|资源不存在                                   |404     |
|4291|触发限流                                    |429     |
|5001|内部服务错误                                  |500     |
|5002|Python Agent 层不可用                       |502     |
|5003|FE 遗忘引擎不可用                              |502     |
|5041|Agent 超时                                |504     |

### 19.2 关键接口完整规范

**POST /api/v1/auth/register（租户注册）**

```
Request:
{
  "brand_name": "某某品牌",        // 2-50 字
  "contact_name": "张三",          // 2-20 字
  "phone": "13800138000",
  "email": "admin@example.com",
  "password": "Abc12345!",         // 8-32位，含大小写+数字
  "verify_code": "123456"
}

Response 200:
{
  "code": 0,
  "data": {
    "tenant_id": 42,
    "status": "pending",
    "message": "申请已提交，预计1个工作日内完成审核"
  }
}

Error Cases:
  4002 → 验证码错误
  4003 → 手机号已注册
  4001 → 密码强度不足
```

**POST /api/v1/chat/message（发送消息）**

```
Request Headers:
  Authorization: Bearer <jwt>         // Web 端
  X-API-Key: mimi_live_xxx            // 平台集成

Request Body:
{
  "session_id": "conv_abc123",        // 选填，不填则自动创建
  "content": "我是油皮，推荐个洗面奶",
  "type": "text",                     // text | image
  "image_url": null,                  // type=image 时填
  "interrupt_reply": false            // 是否为中断回复
}

Response 200:
{
  "code": 0,
  "data": {
    "session_id": "conv_abc123",
    "message_id": "msg_xyz",
    "stage": "agent_running"
  }
}
// SSE 流在 GET /api/v1/chat/stream 订阅
```

**PUT /api/v1/admin/tenants/{id}/approve（审批通过）**

```
Request Headers:
  X-Admin-Key: <admin_api_key>

Response 200:
{
  "code": 0,
  "data": {
    "tenant_id": 42,
    "status": "active",
    "api_key": "mimi_live_xxxxxxxxxx",  // 仅此一次返回明文
    "widget_snippet": "<script src='https://hufu.cn/widget.js' data-tenant-id='42'></script>"
  }
}
```

-----

## 20. [补全] 边界条件与异常流

### 20.1 用户行为边界

|场景                |处理方式                                                 |
|------------------|-----------------------------------------------------|
|用户发消息时 Agent 正在运行 |前台 Agent 回复”正在处理，稍等~”，丢弃该消息（不入队）                     |
|用户连续发 5 条以上消息（被限流）|返回 4291，前端提示”发送太频繁，请稍候”                              |
|用户上传图片但识肤师不可用     |前台 Agent 回复”图片分析暂时不可用，您可以描述皮肤状况”                     |
|识肤师接收到非人脸图片       |VL 模型判定非皮肤图片 → 回复”请上传面部清晰照片”                         |
|问卷师中途用户发其他消息      |视为退出问卷 → SessionState 清空 agent_state → 前台 Agent 处理新消息|
|中断超时（5min 用户未回复）  |使用 options[0] 作为默认答案继续，记录 `interrupt_timed_out=true` |

### 20.2 系统故障边界

|故障场景             |降级方案                                |
|-----------------|------------------------------------|
|Redis 不可用        |SessionState 降级为纯 PG 读写（延迟增加，接受）    |
|FE gRPC 不可用      |fe_retrieve 返回空，fe_ingest 进入本地队列稍后重试|
|Python Agent 层不可用|Go 返回 SSE error 事件，前端展示”服务繁忙，请稍后再试” |
|pgvector 索引损坏    |hybrid_search 降级为仅 keyword 检索       |
|企微 AccessToken 过期|自动刷新，失败则主动推送进入队列重试（最多 3 次）          |
|LLM API 限流       |指数退避重试（1s, 2s, 4s），第 3 次失败返回兜底回复    |

### 20.3 数据边界

|字段           |最大值   |超出处理                                |
|-------------|------|------------------------------------|
|消息内容         |2000 字|截断并提示”消息过长，已截断至2000字”               |
|图片大小         |10MB  |拒绝并提示重新上传                           |
|产品描述         |4000 字|入库时截断，不报错                           |
|Agent 状态 JSON|64KB  |超出则清空非关键字段（如 tool_call_history），记录告警|
|SSE 单事件      |64KB  |大卡片分块推送（SSE multi-event）            |

-----

## 21. [补全] 环境变量与配置清单

### 21.1 Go 层

```env
# 服务配置
PORT=8080
ENV=production                    # production | staging | development
ADMIN_API_KEY=<secret>

# 数据库
DATABASE_URL=postgres://...
REDIS_URL=redis://...

# Python Agent 层
PYTHON_SERVICE_URL=http://localhost:8000
PYTHON_SERVICE_TIMEOUT=35s

# JWT
JWT_SECRET=<secret>
JWT_EXPIRE=24h

# 限流
RATE_LIMIT_GLOBAL=1000           # req/min
RATE_LIMIT_USER_MSG=60           # msg/min

# 平台 Secret 加密密钥
PLATFORM_SECRET_ENCRYPTION_KEY=<aes-256-key>

# 通知
ALERT_WEBHOOK_URL=<internal-webhook>
```

### 21.2 Python 层

```env
# 服务配置
PORT=8000
ENV=production
LOG_LEVEL=INFO

# 数据库
DATABASE_URL=postgres://...
REDIS_URL=redis://...

# LLM
LLM_FLASH_MODEL=qwen-turbo
LLM_PRO_MODEL=qwen-max
LLM_VL_MODEL=qwen-vl-plus
LLM_API_KEY=<secret>
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# Embedding
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMS=1024
EMBEDDING_CACHE_TTL=3600

# FE 遗忘引擎
FE_GRPC_HOST=knownot.cc
FE_GRPC_PORT=50052
FE_GRPC_TIMEOUT=5s

# Observation
TRACE_ENABLED=true
TRACE_SAMPLE_RATE=1.0            # 1.0=全量，0.1=10%采样
```

### 21.3 React 层

```env
VITE_API_BASE_URL=https://api.hufu.cn
VITE_SSE_RECONNECT_MAX=10
VITE_ENV=production
```

-----

## 22. [补全] 阶段依赖关系图

```
阶段一（骨架）
├── 1. DB Migration（所有阶段的基础）
│     └─ 阻塞：2,3,4,6,7
├── 2. Go: 路由 + SSE + Redis SessionState
│     └─ 阻塞：8,9（需要 Go 层才能联调）
├── 3. Python: Orchestrator + BaseAgent + Tool 基类
│     └─ 阻塞：8,9,10,11,12,13
├── 4. React: 初始化 + SSE 连接 + 消息渲染
│     └─ 阻塞：24,25,26（依赖骨架）
├── 5. Proto 更新 + FE GenerateKin
│     └─ 阻塞：8（fe_tool.py 依赖新 proto）
├── 6. RAG: 语义搜索 + 混合检索 + Embedding 缓存
│     └─ 阻塞：10,14（配药师依赖 RAG）
└── 7. Agent 身份层 + Capability Registry
      └─ 阻塞：9,10,11,12（所有子 Agent 依赖）

阶段二（能力迁移，需阶段一全部完成）
├── 8. FE Tool（fe_retrieve/fe_ingest）    → 依赖 3,5
├── 9. 前台 Agent + 自由对话 + RAG Tool    → 依赖 3,6,7,8
├── 10. 配药师 Agent                        → 依赖 6,7,8,9
├── 11. 问卷师 Agent                        → 依赖 3,7,8
├── 12. 识肤师 Agent                        → 依赖 3,7,8
├── 13. 日报官 Agent                        → 依赖 3,7,8
├── 14. 产品录入 Tool + 向量化              → 依赖 6
├── 15. Observation Layer 遥测              → 依赖 9,10,11,12（各 Agent 埋点）
└── 16. Reflection Agent                   → 依赖 8,15（写记忆+读遥测）

阶段三（平台+运营，需阶段二核心完成：9,10）
├── 17. 租户注册 + 审批流                  → 依赖 DB Migration
├── 18. 企微适配器                          → 依赖 9（前台 Agent 可用）
├── 19. 抖音适配器                          → 依赖 18（复用企微框架）
├── 20. 小红书适配器                        → 依赖 18
├── 21. Knowledge Pipeline                 → 依赖 6,14
├── 22. Human Escalation                   → 依赖 9（前台 Agent 中加规则引擎）
└── 23. Agent Journal                      → 依赖 15,16

阶段四（前端+上线，并行于阶段三）
├── 24-26. 卡片组件                         → 依赖 4（React 骨架），各 Agent 输出格式
├── 27. 评价看板                            → 依赖 15,16
├── 28. widget.js 嵌入升级                 → 依赖 2（Go 路由）
├── 29. B端管理后台                         → 依赖 17
├── 30. PWA                                → 依赖 4
└── 31. 全量切换                            → 阶段四全部完成 + 压测通过
```

-----

*文档版本：v0.3-dev，生成日期：2026-06-07*
*基于原始 PRD 升级，新增内容均以 `[补全]` 标记。*