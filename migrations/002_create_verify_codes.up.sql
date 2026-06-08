-- 002_create_verify_codes.up.sql
-- Step 2: CREATE TABLE verify_codes (无依赖)
-- 迁移工具: golang-migrate

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
