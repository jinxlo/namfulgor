-- Namwoo Database Schema
-- PostgreSQL dialect

-- Ensure the database is connected before running this script.
-- Example psql command: \c namwoo_db

-- 1. Enable pgvector extension (Required for vector similarity search)
-- This needs to be run by a superuser or user with sufficient privileges ONE TIME per database.
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Table for storing product information synced from WooCommerce
CREATE TABLE IF NOT EXISTS products ( -- <<< MODIFIED: Added IF NOT EXISTS
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
-- Optional: Index for basic text search on name (consider if needed without Dialogflow)
-- CREATE INDEX IF NOT EXISTS idx_products_name ON products USING gin(to_tsvector('english', name));


-- Create an index for vector similarity search (Using HNSW as default)
CREATE INDEX IF NOT EXISTS idx_products_embedding_hnsw ON products USING hnsw (embedding vector_cosine_ops);

-- Grant permissions (adjust username 'namwoo_user' as needed - commented out by default)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE products TO namwoo_user;
-- GRANT USAGE, SELECT ON SEQUENCE products_id_seq TO namwoo_user;

-- Optional: Add comments to tables/columns for clarity
COMMENT ON TABLE products IS 'Stores product information synchronized from WooCommerce, including vector embeddings for semantic search.';
COMMENT ON COLUMN products.embedding IS 'Vector embedding generated from product text (name, description, etc.) used for similarity search.';


-- 3. Table for storing human takeover pause state per Support Board conversation (NEW)
-- Keeping IF NOT EXISTS here too, although it likely didn't run before due to the error
CREATE TABLE IF NOT EXISTS conversation_pauses (
    conversation_id VARCHAR(255) PRIMARY KEY, -- Support Board Conversation ID (Using VARCHAR as SB IDs can be strings or large numbers)
    paused_until TIMESTAMP WITH TIME ZONE NOT NULL -- Timestamp (UTC) until which the bot should remain paused for this conversation
);

-- Optional: Add comments for clarity
COMMENT ON TABLE conversation_pauses IS 'Tracks when a bot should pause responding to a specific Support Board conversation due to human agent intervention.';
COMMENT ON COLUMN conversation_pauses.conversation_id IS 'The unique ID of the Support Board conversation being paused.';
COMMENT ON COLUMN conversation_pauses.paused_until IS 'The UTC timestamp until which the bot should not respond automatically to this conversation.';

-- Grant permissions (adjust username 'namwoo_user' if you use specific users - commented out by default)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE conversation_pauses TO namwoo_user;


-- End of schema definition