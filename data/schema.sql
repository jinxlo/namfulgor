-- Namwoo Database Schema
-- PostgreSQL dialect

-- Ensure the database is connected before running this script.
-- Example psql command: \c namwoo_db

-- 1. Enable pgvector extension (Required for vector similarity search)
-- This needs to be run by a superuser or user with sufficient privileges ONE TIME per database.
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Table for storing product information synced from WooCommerce
CREATE TABLE products (
    id SERIAL PRIMARY KEY,                     -- Internal auto-incrementing primary key
    wc_product_id BIGINT UNIQUE NOT NULL,      -- WooCommerce Product ID (unique identifier from WC)
    sku VARCHAR(255) UNIQUE,                   -- Product Stock Keeping Unit (unique, indexed)
    name VARCHAR(512) NOT NULL,                -- Product name
    description TEXT,                          -- Full product description from WC
    short_description TEXT,                    -- Short product description from WC
    searchable_text TEXT,                      -- Pre-combined text for embedding and potential full-text search
    price NUMERIC(12, 2),                      -- Product price (adjust precision/scale if needed)
    stock_status VARCHAR(50),                  -- Stock status text ('instock', 'outofstock', 'onbackorder')
    stock_quantity INT,                        -- Actual stock count (can be null if not managed)
    manage_stock BOOLEAN,                      -- Whether stock is managed at the product level in WC
    permalink VARCHAR(1024),                   -- Product URL
    categories TEXT,                           -- Concatenated category names (e.g., "Clothing, T-Shirts")
    tags TEXT,                                 -- Concatenated tag names (e.g., "Sale, Cotton")
    embedding vector(1536),                    -- The vector embedding (dimension MUST match config.EMBEDDING_DIMENSION)
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP -- Timestamp of the last sync update
);

-- Add indexes for common query filters and lookups
CREATE INDEX IF NOT EXISTS idx_products_wc_product_id ON products (wc_product_id);
CREATE INDEX IF NOT EXISTS idx_products_sku ON products (sku);
CREATE INDEX IF NOT EXISTS idx_products_stock_status ON products (stock_status);
CREATE INDEX IF NOT EXISTS idx_products_name ON products USING gin(to_tsvector('english', name)); -- Optional: Index for basic text search on name


-- Create an index for vector similarity search (CHOOSE ONE METHOD AND TUNE PARAMETERS)
-- Method 1: HNSW (Hierarchical Navigable Small Worlds) - Generally good balance of speed/accuracy
-- Adjust 'm' and 'ef_construction' based on dataset size and performance needs.
-- vector_cosine_ops is common for text embeddings.
CREATE INDEX IF NOT EXISTS idx_products_embedding_hnsw ON products USING hnsw (embedding vector_cosine_ops);

-- Method 2: IVFFlat (Inverted File Flat) - Can be faster for very large datasets but requires tuning 'lists'.
-- 'lists' should be chosen carefully, e.g., sqrt(N) to N/1000 where N is the number of rows. Start maybe with 100?
-- CREATE INDEX IF NOT EXISTS idx_products_embedding_ivfflat ON products USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Grant permissions (adjust username 'namwoo_user' as needed)
-- It's often better to manage permissions separately, but included here for completeness.
-- GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE products TO namwoo_user;
-- GRANT USAGE, SELECT ON SEQUENCE products_id_seq TO namwoo_user;


-- 3. Table for storing conversation history per Dialogflow session
CREATE TABLE conversation_history (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,          -- Dialogflow session ID (extracted from request)
    history JSONB NOT NULL,                    -- Stores the entire conversation as a JSON array of objects
                                               -- e.g., [{'role': 'system', 'content': '...'}, {'role': 'user', 'content': '...'}, ...]
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, -- When the session history was first created
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP -- When the session history was last modified
);

-- Add index for fast lookup by session ID
CREATE INDEX IF NOT EXISTS idx_conversation_history_session_id ON conversation_history (session_id);

-- Create a trigger function to automatically update 'last_updated_at' on history changes
CREATE OR REPLACE FUNCTION update_history_timestamp()
RETURNS TRIGGER AS $$
BEGIN
   NEW.last_updated_at = CURRENT_TIMESTAMP;
   RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply the trigger to the conversation_history table
DROP TRIGGER IF EXISTS trg_update_history_timestamp ON conversation_history; -- Drop existing trigger if recreating
CREATE TRIGGER trg_update_history_timestamp
BEFORE UPDATE ON conversation_history
FOR EACH ROW
EXECUTE FUNCTION update_history_timestamp();

-- Grant permissions (adjust username 'namwoo_user' as needed)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE conversation_history TO namwoo_user;
-- GRANT USAGE, SELECT ON SEQUENCE conversation_history_id_seq TO namwoo_user;


-- Optional: Add comments to tables/columns for clarity
COMMENT ON TABLE products IS 'Stores product information synchronized from WooCommerce, including vector embeddings for semantic search.';
COMMENT ON COLUMN products.embedding IS 'Vector embedding generated from product text (name, description, etc.) used for similarity search.';
COMMENT ON TABLE conversation_history IS 'Stores the turn-by-turn conversation history for each Dialogflow session.';
COMMENT ON COLUMN conversation_history.history IS 'JSONB array containing message objects with role and content.';

-- End of schema definition