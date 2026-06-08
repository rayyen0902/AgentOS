-- 010_idx_products_embedding.up.sql
-- Step 9: CREATE INDEX idx_products_embedding
-- CONCURRENTLY 不能在事务内执行，必须作为独立迁移脚本
-- 迁移工具: golang-migrate (disableTransaction: true)

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_products_embedding
    ON products USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
