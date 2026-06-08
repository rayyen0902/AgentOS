-- 004_create_tenant_platforms.up.sql
-- Step 4: CREATE TABLE tenant_platforms (依赖 tenants)
-- 迁移工具: golang-migrate

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
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
