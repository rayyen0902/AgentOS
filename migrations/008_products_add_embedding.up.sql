-- 008_products_add_embedding.up.sql
-- Step 8: ALTER TABLE products ADD COLUMN embedding (需先有 pgvector 扩展)
-- 迁移工具: golang-migrate

CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE products ADD COLUMN IF NOT EXISTS embedding vector(1024);
