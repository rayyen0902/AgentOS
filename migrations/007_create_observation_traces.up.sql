-- 007_create_observation_traces.up.sql
-- Step 7: CREATE TABLE observation_traces (无外键，可独立)
-- 迁移工具: golang-migrate

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
