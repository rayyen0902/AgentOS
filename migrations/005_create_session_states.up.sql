-- 005_create_session_states.up.sql
-- Step 5: CREATE TABLE session_states (无外键，可独立)
-- 迁移工具: golang-migrate
-- Note: user_id/tenant_id 故意不加外键约束 (PRD 设计如此，避免跨库约束复杂化)

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
    ttl_seconds  INT DEFAULT 1800,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_session_states_user ON session_states(user_id);
CREATE INDEX IF NOT EXISTS idx_session_states_updated ON session_states(updated_at);
