-- initial_data_scripts/init_pgvector.sql
CREATE EXTENSION IF NOT EXISTS vector;
COMMENT ON EXTENSION vector IS 'pgvector extension for vector similarity search (optional for NamFulgor if not using embeddings for batteries)';