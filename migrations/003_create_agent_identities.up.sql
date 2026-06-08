-- 003_create_agent_identities.up.sql
-- Step 3: CREATE TABLE agent_identities (依赖 tenants)
-- 迁移工具: golang-migrate

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
