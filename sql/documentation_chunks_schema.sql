-- Documentation Chunks Schema for BM25 Search
-- This replaces Pinecone vector search with PostgreSQL BM25 full-text search

-- Ensure ParadeDB search extension is available
CREATE EXTENSION IF NOT EXISTS pg_search;

-- Drop existing objects if they exist (for clean reinstalls)
DROP INDEX IF EXISTS idx_documentation_chunks_bm25;
DROP TABLE IF EXISTS documentation_chunks;

-- Create the main documentation chunks table
CREATE TABLE documentation_chunks (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,                    -- Chunk content (same as Pinecone metadata.text)
    source TEXT NOT NULL,                  -- Relative file path (same as Pinecone metadata.source)
    title TEXT NOT NULL,                   -- Document title (same as Pinecone metadata.title)
    chunk_size INTEGER,                    -- Length of text content for analytics
    created_at TIMESTAMP DEFAULT NOW(),   -- When chunk was indexed
    updated_at TIMESTAMP DEFAULT NOW()    -- Last update timestamp
);

-- Create indexes for performance
CREATE INDEX idx_documentation_chunks_source ON documentation_chunks(source);
CREATE INDEX idx_documentation_chunks_title ON documentation_chunks(title);
CREATE INDEX idx_documentation_chunks_created_at ON documentation_chunks(created_at);

-- ParadeDB BM25 full-text search index
-- Note: ParadeDB uses pg_search extension (already included) with 'bm25' access method
CREATE INDEX idx_documentation_chunks_bm25 ON documentation_chunks
USING bm25 (id, text, title) WITH (key_field='id');

-- Helper function to get document statistics
CREATE OR REPLACE FUNCTION get_documentation_stats()
RETURNS TABLE(
    total_chunks BIGINT,
    total_documents BIGINT,
    avg_chunk_size NUMERIC,
    last_updated TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*) as total_chunks,
        COUNT(DISTINCT source) as total_documents,
        AVG(chunk_size) as avg_chunk_size,
        MAX(updated_at) as last_updated
    FROM documentation_chunks;
END;
$$ LANGUAGE plpgsql;

-- Helper function to search documentation (will be enhanced with BM25)
CREATE OR REPLACE FUNCTION search_documentation_basic(
    search_query TEXT,
    max_results INTEGER DEFAULT 10
)
RETURNS TABLE(
    id INTEGER,
    text TEXT,
    source TEXT,
    title TEXT,
    relevance_score REAL
) AS $$
BEGIN
    -- Basic PostgreSQL full-text search (fallback if BM25 not available)
    RETURN QUERY
    SELECT
        dc.id,
        dc.text,
        dc.source,
        dc.title,
        ts_rank(to_tsvector('english', dc.text || ' ' || dc.title), plainto_tsquery('english', search_query))::REAL as relevance_score
    FROM documentation_chunks dc
    WHERE to_tsvector('english', dc.text || ' ' || dc.title) @@ plainto_tsquery('english', search_query)
    ORDER BY relevance_score DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Update trigger to maintain updated_at timestamp
CREATE OR REPLACE FUNCTION update_documentation_chunks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    NEW.chunk_size = LENGTH(NEW.text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_documentation_chunks_updated_at
    BEFORE UPDATE ON documentation_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_documentation_chunks_updated_at();

-- Insert trigger to set chunk_size
CREATE TRIGGER trg_documentation_chunks_insert
    BEFORE INSERT ON documentation_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_documentation_chunks_updated_at();

-- Grant permissions (adjust based on your user setup)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON documentation_chunks TO your_app_user;
-- GRANT USAGE, SELECT ON SEQUENCE documentation_chunks_id_seq TO your_app_user;

-- Sample query examples for reference:
-- 1. Basic search:
--    SELECT * FROM search_documentation_basic('OPAL filter syntax', 5);
--
-- 2. Document statistics:
--    SELECT * FROM get_documentation_stats();
--
-- 3. Find all chunks from a specific document:
--    SELECT * FROM documentation_chunks WHERE source = 'path/to/document.md';
--
-- 4. ParadeDB BM25 search (@@@ operator):
--    SELECT id, text, source, title
--    FROM documentation_chunks
--    WHERE text @@@ 'search query' OR title @@@ 'search query'
--    ORDER BY paradedb.score(id) DESC LIMIT 10;