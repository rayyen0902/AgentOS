-- 011_add_wecom_agent_id.up.sql
-- S7-07: Add wecom_agent_id column to tenant_platforms
-- 企微 AgentID, default 1000002 per WeCom standard

ALTER TABLE tenant_platforms
    ADD COLUMN IF NOT EXISTS wecom_agent_id INTEGER DEFAULT 1000002;
