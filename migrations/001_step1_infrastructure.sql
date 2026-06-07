-- Step 1: ALTER TABLE tenants (无依赖)
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS phone VARCHAR(32);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'active';
-- status: pending | active | suspended | rejected

-- Step 2: CREATE TABLE verify_codes (无依赖)
CREATE TABLE IF NOT EXISTS verify_codes (
    id BIGSERIAL PRIMARY KEY,
    target VARCHAR(255),
    code VARCHAR(8),
    type VARCHAR(16),
    expires_at TIMESTAMPTZ,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_verify_codes_target ON verify_codes(target, used);

-- Step 3: CREATE TABLE agent_identities (依赖 tenants)
CREATE TABLE IF NOT EXISTS agent_identities (
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

-- Step 4: CREATE TABLE tenant_platforms (依赖 tenants)
CREATE TABLE IF NOT EXISTS tenant_platforms (
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

-- Step 5: CREATE TABLE session_states (无外键，可独立)
CREATE TABLE IF NOT EXISTS session_states (
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
CREATE INDEX IF NOT EXISTS idx_session_states_user ON session_states(user_id);
CREATE INDEX IF NOT EXISTS idx_session_states_updated ON session_states(updated_at);

-- Step 6: CREATE TABLE agent_audit_log (无外键，可独立)
CREATE TABLE IF NOT EXISTS agent_audit_log (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64),
    agent_name VARCHAR(64),
    event_type VARCHAR(32),
    event_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_session ON agent_audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON agent_audit_log(created_at);

-- Step 7: CREATE TABLE observation_traces (无外键，可独立)
CREATE TABLE IF NOT EXISTS observation_traces (
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
CREATE INDEX IF NOT EXISTS idx_traces_session ON observation_traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_created ON observation_traces(created_at);

-- Step 8: ALTER TABLE products ADD COLUMN embedding (需先有 pgvector 扩展)
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE products ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- Step 9: CREATE INDEX idx_products_embedding (在 Step 8 后，可后台 CONCURRENTLY 创建)
-- Note: CONCURRENTLY 不能在事务内运行，使用 IF NOT EXISTS 时先检查
CREATE INDEX IF NOT EXISTS idx_products_embedding ON products USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Step 10: CREATE TABLE knowledge.product_conflicts (依赖 products)
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE TABLE IF NOT EXISTS knowledge.product_conflicts (
    id SERIAL PRIMARY KEY,
    product_a_id BIGINT REFERENCES products(id),
    product_b_id BIGINT REFERENCES products(id),
    conflict_type VARCHAR(32),
    severity VARCHAR(8),
    description TEXT,
    suggestion TEXT
);
