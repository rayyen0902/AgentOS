-- 009_create_knowledge_product_conflicts.up.sql
-- Step 10: CREATE TABLE knowledge.product_conflicts (依赖 products)
-- 迁移工具: golang-migrate

CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE TABLE IF NOT EXISTS knowledge.product_conflicts (
    id BIGSERIAL PRIMARY KEY,
    product_a_id BIGINT REFERENCES products(id),
    product_b_id BIGINT REFERENCES products(id),
    conflict_type VARCHAR(32),
    severity VARCHAR(8),
    description TEXT,
    suggestion TEXT
);
