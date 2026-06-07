# Step 3：Go 骨架

> **上下文范围**：PRD 第 3（全异步架构）、第 10（消息投递）、第 15 节（Go 层重构）、第 19 节（接口契约与错误码）
> **前置依赖**：Step 1（DB + Redis + 环境变量）
> **完成标准**：Go HTTP 服务可启动，SSE 端点可用，SessionState Redis 读写正常，Go→Python 转发通路打通

---

## 3.1 技术栈与设计原则

- Go 1.22+，标准 `net/http`
- **不做**：不调 LLM、不写 Agent 逻辑
- **只做**：路由 + 鉴权 + SessionState + 平台回调 + Webhook 验证

---

## 3.2 全异步架构

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
    ▼ (异步 goroutine)
子 Agent 后台执行
    │
    ▼
Go: SessionState → 事件队列 → 平台主动推送
    企微: POST /cgi-bin/message/send
    抖音: POST /im/send_msg/
    Web:  SSE push
```

### 消息时序（以企微为例）

```
T+0ms     企微服务器 POST 用户消息到 Webhook
T+200ms   Go 验签 → 归一化 → 转发 Python
T+400ms   前台 Agent 回复 → Go 被动回复 200 OK
T+800ms   子 Agent 启动（后台 goroutine）
T+1.2s    子 Agent: FE 检索完成
T+3.0s    子 Agent: 产品匹配完成
T+3.1s    Go 主动调用企微 API 推送结果卡片
```

### 各渠道投递方式

| 渠道 | 被动回复（同步） | 主动推送（异步） | 中断反调 |
|------|-----------------|-----------------|----------|
| 企微 | Webhook 200 响应 XML | POST `/cgi-bin/message/send` | 主动推送文本+按钮卡片 |
| 抖音 | Webhook 200 响应 | POST `/im/send_msg/` | 主动推送文本+选项 |
| 小红书 | Webhook 200 响应 | 私信 API | 主动推送文本+选项 |
| Web Demo | HTTP 200 | SSE / 轮询(降级) | SSE push InterruptCard |

### 后台任务超时与取消策略

| Agent | 超时时间 | 超时后行为 |
|-------|---------|-----------|
| 前台 Agent | 3s | 返回兜底回复"稍后再试" + 记录告警 |
| 配药师 | 30s | 主动推送"分析超时，已记录，稍后重试" |
| 识肤师 | 30s | 同上 |
| 问卷师 | 600s（单步 30s） | 单步超时 → 重发当前问题 |
| 日报官 | 20s | 跳过本次推送，下次触发时重试 |

---

## 3.3 路由表

| 方法 | 路径 | 功能 | 鉴权 |
|------|------|------|------|
| `GET` | `/health` | 健康检查 | 无 |
| `POST` | `/api/v1/auth/register` | 租户注册 | 无 |
| `POST` | `/api/v1/auth/login` | 登录 | 无 |
| `POST` | `/api/v1/auth/send-code` | 发送验证码 | RateLimit |
| `POST` | `/api/v1/chat/message` | 发送消息 | JWT / API Key |
| `GET` | `/api/v1/chat/stream` | SSE 订阅 | JWT |
| `POST` | `/api/v1/webhook/wecom/{tenant_id}` | 企微回调 | 签名验证 |
| `POST` | `/api/v1/webhook/douyin/{tenant_id}` | 抖音回调 | 签名验证 |
| `POST` | `/api/v1/webhook/xhs/{tenant_id}` | 小红书回调 | 签名验证 |
| `GET` | `/api/v1/admin/tenants` | 租户列表 | Admin Key |
| `PUT` | `/api/v1/admin/tenants/{id}/approve` | 审批通过 | Admin Key |
| `GET` | `/api/v1/admin/tenants/{id}` | 租户详情 | Admin Key |

---

## 3.4 中间件

| 中间件 | 作用 | 配置 |
|--------|------|------|
| RequestID | 注入 trace_id | 每请求生成 UUID |
| Auth | JWT 验证（B端）/ API Key 验证（平台） | 白名单：`/health`、`/api/v1/auth/*`、`/api/v1/webhook/*` |
| RateLimit | 接口限流 | 全局 1000 req/min，单用户 60 msg/min |
| Recovery | panic 恢复 | 返回 500，记录堆栈 |
| Logger | 结构化日志 | JSON 格式，含 trace_id / user_id / duration_ms |

---

## 3.5 统一响应结构

```go
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

---

## 3.6 统一错误码

| 错误码 | 含义 | HTTP 状态码 |
|--------|------|------------|
| 0 | 成功 | 200 |
| 4001 | 参数校验失败 | 400 |
| 4002 | 验证码错误/过期 | 400 |
| 4003 | 手机号/邮箱已注册 | 400 |
| 4011 | 未登录/Token 无效 | 401 |
| 4012 | API Key 无效 | 401 |
| 4031 | 无权限（租户间隔离） | 403 |
| 4032 | 租户状态非 active | 403 |
| 4041 | 资源不存在 | 404 |
| 4291 | 触发限流 | 429 |
| 5001 | 内部服务错误 | 500 |
| 5002 | Python Agent 层不可用 | 502 |
| 5003 | FE 遗忘引擎不可用 | 502 |
| 5041 | Agent 超时 | 504 |

---

## 3.7 SSE 事件类型完整规范

| event 名 | 触发时机 | data 格式 |
|----------|---------|-----------|
| `status` | Tool/Agent 状态变化 | `{"seq":1,"source":"tool:fe_retrieve","status":"running","label":"..."}` |
| `reply` | 文本回复就绪 | `{"text":"...", "from":"front_agent"}` |
| `interrupt` | 子 Agent 需要确认 | InterruptRequest JSON |
| `card` | 卡片数据就绪 | CardPayload JSON |
| `done` | 本轮全部完成 | `{"session_id":"...","total_ms":3500}` |
| `error` | Agent 报错 | `{"code":"AGENT_TIMEOUT","message":"..."}` |
| `heartbeat` | 每 30s 保活 | `{}` |

所有事件都带 `session_id` 字段，前端按 session_id 路由。

---

## 3.8 SessionState 管理

### 状态流转

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

### 异常状态流转

```
agent_running
  │ 超时 / Tool 三次失败
  ▼
error
  │ 错误信息写入 SessionState.error_info
  ▼
idle（自动恢复，可接受下条消息）

agent_interrupted
  │ interrupt.timeout_s 到期且用户未回复
  ▼
agent_running（使用默认选项 options[0] 继续）
```

### SessionState 字段完整定义

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 是 | 格式：`conv_{uuid4_hex[:16]}` |
| `stage` | enum | 是 | `idle` / `agent_running` / `agent_interrupted` / `error` |
| `current_agent` | string\|null | 否 | 运行中的 Agent 名，idle 时为 null |
| `agent_state` | object | 否 | Agent 自定义状态，由 Agent 负责序列化 |
| `interrupt` | InterruptRequest\|null | 否 | |
| `status_stream` | StatusEvent[] | 是 | 初始为 `[]` |
| `user_id` | bigint | 是 | |
| `tenant_id` | bigint | 是 | |
| `platform` | string | 是 | `web` / `wecom` / `douyin` / `xhs` |
| `created_at` | ISO8601 | 是 | |
| `updated_at` | ISO8601 | 是 | 每次写入更新 |
| `ttl_seconds` | int | 是 | 默认 1800（30min） |

### 持久化策略

- **Redis**：热状态（TTL 30min），快速读写
- **PostgreSQL** `session_states`：冷存储 + 审计
- Redis 不可用 → 降级为纯 PG 读写

### Redis Key 规范

```
session:{session_id}            → SessionState JSON（TTL 1800s）
sse_channel:{session_id}        → Redis Stream（SSE 事件队列，TTL 3600s）
agent_lock:{session_id}         → 分布式锁（TTL = agent 超时时间，防并发）
access_token:wecom:{corp_id}    → 企微 AccessToken（TTL = expires_in - 60s）
```

### 并发控制

- 同一 session_id 同一时刻只允许一个 Agent 运行（`agent_lock:{session_id}` Redis 锁）
- 新消息到达时若 stage = `agent_running`：回复"正在处理上一条，稍等~"，不启动新 Agent
- 新消息到达时若 stage = `agent_interrupted`：视为中断回复，路由至 `agent.resume()`

---

## 3.9 Go → Python 通信规范

- 协议：HTTP POST（本地回环）
- 超时：`context.WithTimeout(30s)`（与 Agent 最大超时对齐）
- 重试：不重试（Python 侧幂等性由 session_id 保证）
- 错误处理：Python 返回非 200 → Go 推送 SSE error 事件 → 前端展示兜底提示
- Python base URL 从 `PYTHON_SERVICE_URL` 环境变量读取

---

## 3.10 验收标准

- [ ] Go 服务启动，`/health` 返回 200
- [ ] 所有路由注册完成（含中间件链）
- [ ] `GET /api/v1/chat/stream` SSE 连接正常，heartbeat 每 30s 推送
- [ ] SessionState Redis 读写正常（get / set / delete + TTL）
- [ ] `POST /api/v1/chat/message` 转发到 Python `/agent/run` 并返回
- [ ] 统一错误码中间件生效（401 未登录返回 4011）
- [ ] RequestID 注入 + Logger 结构化日志输出
- [ ] RateLimit 限流生效（全局 + 单用户）
- [ ] Recovery 中间件捕获 panic 并返回 5001
