-- 011_add_wecom_agent_id.down.sql
-- S7-07: Remove wecom_agent_id column

ALTER TABLE tenant_platforms
    DROP COLUMN IF EXISTS wecom_agent_id;
