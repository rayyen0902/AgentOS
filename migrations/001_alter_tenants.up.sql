-- 001_alter_tenants.up.sql
-- Step 1: ALTER TABLE tenants (无依赖)
-- 迁移工具: golang-migrate

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS phone VARCHAR(32);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'active';
-- status: pending | active | suspended | rejected
