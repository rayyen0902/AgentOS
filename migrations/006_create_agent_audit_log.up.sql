-- 006_create_agent_audit_log.up.sql
-- Step 6: CREATE TABLE agent_audit_log (无外键，可独立)
-- 迁移工具: golang-migrate

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
