# Step 1：基础设施

> **上下文范围**：PRD 第 2、4、13、21 节
> **前置依赖**：无
> **完成标准**：DB 13 张表迁移成功，Redis 连接正常，环境变量配置就绪

---

## 1.1 技术栈版本锁定

| 组件 | 版本 | 备注 |
|------|------|------|
| Go | 1.22+ | 泛型 + 标准 net/http |
| Python | 3.11+ | asyncio 完善 |
| FastAPI | 0.111+ | |
| React | 18.3+ | concurrent features |
| Vite | 5.x | |
| TypeScript | 5.x | |
| Redis | 7.x | TTL + Stream 支持 |
| PostgreSQL | 15+ | pgvector 扩展 |
| pgvector | 0.7+ | ivfflat 索引 |

---

## 1.2 非功能性约束

| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| 前台 Agent 首次响应 | ≤ 500ms（p95） | Observation Layer trace |
| 子 Agent 总耗时 | ≤ 5s（p95） | Observation Layer trace |
| SSE 事件到达延迟 | ≤ 200ms | 前端打点 |
| Redis SessionState 读写 | ≤ 10ms（p99） | 服务监控 |
| 系统可用性 | ≥ 99.5% | 月度统计 |
| 单 Agent 最大 token 消耗 | Pro ≤ 8000 tokens/次，Flash ≤ 2000 tokens/次 | Observation Layer |

---

## 1.3 数据库 Migration

### 执行顺序

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

### 现有表变更

```sql
ALTER TABLE tenants ADD COLUMN email VARCHAR(255);
ALTER TABLE tenants ADD COLUMN phone VARCHAR(32);
ALTER TABLE tenants ADD COLUMN password_hash VARCHAR(255);
ALTER TABLE tenants ADD COLUMN status VARCHAR(16) DEFAULT 'active';
-- status: pending | active | suspended | rejected

ALTER TABLE products ADD COLUMN embedding vector(1024);
CREATE INDEX idx_products_embedding ON products USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

### 新增表

```sql
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
    app_secret_hash VARCHAR(256),
    app_secret_encrypted TEXT,
    token VARCHAR(128),
    encoding_aes_key VARCHAR(256),
    webhook_url VARCHAR(512),
    status VARCHAR(16) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

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

-- 产品冲突检测
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

### 保留不变的表

`skin_profiles`, `products`(主体), `user_products`, `schedules`, `conversations`, `messages`, `billing_records`, `facts`

---

## 1.4 Redis Key 规范

```
session:{session_id}            → SessionState JSON（TTL 1800s）
sse_channel:{session_id}        → Redis Stream（SSE 事件队列，TTL 3600s）
agent_lock:{session_id}         → 分布式锁（TTL = agent 超时时间，防并发）
access_token:wecom:{corp_id}    → 企微 AccessToken（TTL = expires_in - 60s）
embed_cache:{sha256(text)}      → Embedding 向量（TTL 3600s）
```

要求：
- 封装 Redis 读写工具类/模块，统一 Key 前缀
- 所有 Key 设置合理 TTL
- 提供 Redis 不可用时的降级策略（SessionState 降级为纯 PG 读写）

---

## 1.5 环境变量

### Go 层 (.env)

```env
PORT=8080
ENV=production                    # production | staging | development
ADMIN_API_KEY=<secret>

DATABASE_URL=postgres://...
REDIS_URL=redis://...

PYTHON_SERVICE_URL=http://localhost:8000
PYTHON_SERVICE_TIMEOUT=35s

JWT_SECRET=<secret>
JWT_EXPIRE=24h

RATE_LIMIT_GLOBAL=1000           # req/min
RATE_LIMIT_USER_MSG=60           # msg/min

PLATFORM_SECRET_ENCRYPTION_KEY=<aes-256-key>

ALERT_WEBHOOK_URL=<internal-webhook>
```

### Python 层 (.env)

```env
PORT=8000
ENV=production
LOG_LEVEL=INFO

DATABASE_URL=postgres://...
REDIS_URL=redis://...

LLM_FLASH_MODEL=qwen-turbo
LLM_PRO_MODEL=qwen-max
LLM_VL_MODEL=qwen-vl-plus
LLM_API_KEY=<secret>
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMS=1024
EMBEDDING_CACHE_TTL=3600

FE_GRPC_HOST=knownot.cc
FE_GRPC_PORT=50052
FE_GRPC_TIMEOUT=5s

TRACE_ENABLED=true
TRACE_SAMPLE_RATE=1.0
```

### React 层 (.env)

```env
VITE_API_BASE_URL=https://api.hufu.cn
VITE_SSE_RECONNECT_MAX=10
VITE_ENV=production
```

---

## 1.6 验收标准

- [ ] 所有 Migration 执行成功，13 张表（含变更）全部就位
- [ ] `config.py` 加载所有 Python 环境变量，含默认值和校验
- [ ] `config.go` 加载所有 Go 环境变量，含默认值和校验
- [ ] Redis 连接正常，`PING` 返回 `PONG`
- [ ] Redis Key 工具类封装完成（get/set/delete + TTL + 前缀）
- [ ] PostgreSQL 连接正常，pgvector 扩展已启用
- [ ] `idx_products_embedding` ivfflat 索引创建成功
- [ ] Redis 不可用时降级到 PG 读写的逻辑就绪
