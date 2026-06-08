-- AgentOS database initialization
-- This runs automatically on first PostgreSQL container start

-- Enable pgvector extension for vector search
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify extension was created
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
