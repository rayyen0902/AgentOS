-- 001_alter_tenants.down.sql
ALTER TABLE tenants DROP COLUMN IF EXISTS email;
ALTER TABLE tenants DROP COLUMN IF EXISTS phone;
ALTER TABLE tenants DROP COLUMN IF EXISTS password_hash;
ALTER TABLE tenants DROP COLUMN IF EXISTS status;
