-- Skills Intelligence Schema
-- Fast skill documentation search using ParadeDB BM25
-- This provides local, offline documentation search without external API dependencies

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pg_search;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Drop old table and indexes if they exist
DROP TABLE IF EXISTS skills_intelligence CASCADE;

-- Drop old BM25 index if it exists
DROP INDEX IF EXISTS skills_search_idx;

-- Main skills intelligence table
CREATE TABLE IF NOT EXISTS skills_intelligence (
    -- Identity
    skill_id VARCHAR(255) PRIMARY KEY,
    skill_name VARCHAR(500) NOT NULL,

    -- Content
    description TEXT NOT NULL,
    content TEXT NOT NULL,

    -- Metadata
    category VARCHAR(100), -- e.g., "Aggregation", "Filtering", "Analysis"
    tags TEXT[], -- e.g., ['statsby', 'aggregation', 'grouping']
    difficulty VARCHAR(20), -- 'beginner', 'intermediate', 'advanced'

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create BM25 index using ParadeDB for fast ranked search
-- This gives us much better ranking than PostgreSQL full-text search
CREATE INDEX skills_search_idx ON skills_intelligence
USING bm25 (skill_id, skill_name, description, content, category, tags, difficulty)
WITH (key_field='skill_id');

-- Indexes for filtering
CREATE INDEX IF NOT EXISTS idx_skills_category ON skills_intelligence (category);
CREATE INDEX IF NOT EXISTS idx_skills_tags ON skills_intelligence USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_skills_difficulty ON skills_intelligence (difficulty);

-- Trigram indexes for fuzzy matching (fallback if BM25 doesn't match)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_skills_name_trgm ON skills_intelligence USING GIN (skill_name gin_trgm_ops);

-- Helper function to search skills with BM25 ranking
CREATE OR REPLACE FUNCTION search_skills_bm25(
    search_query TEXT,
    max_results INTEGER DEFAULT 5,
    category_filter TEXT DEFAULT NULL,
    difficulty_filter TEXT DEFAULT NULL
)
RETURNS TABLE (
    skill_id TEXT,
    skill_name TEXT,
    description TEXT,
    content TEXT,
    category TEXT,
    tags TEXT[],
    difficulty TEXT,
    relevance_score REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.skill_id::TEXT,
        s.skill_name::TEXT,
        s.description::TEXT,
        s.content::TEXT,
        s.category::TEXT,
        s.tags,
        s.difficulty::TEXT,
        paradedb.score(s.skill_id)::REAL as relevance_score
    FROM skills_intelligence s
    WHERE s.skill_id @@@ paradedb.parse(search_query, lenient => true)
      AND (category_filter IS NULL OR s.category = category_filter)
      AND (difficulty_filter IS NULL OR s.difficulty = difficulty_filter)
    ORDER BY paradedb.score(s.skill_id) DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Fallback fuzzy search function (when BM25 doesn't find exact matches)
CREATE OR REPLACE FUNCTION search_skills_fuzzy(
    search_query TEXT,
    max_results INTEGER DEFAULT 5
)
RETURNS TABLE (
    skill_id TEXT,
    skill_name TEXT,
    description TEXT,
    content TEXT,
    category TEXT,
    tags TEXT[],
    difficulty TEXT,
    similarity_score REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.skill_id::TEXT,
        s.skill_name::TEXT,
        s.description::TEXT,
        s.content::TEXT,
        s.category::TEXT,
        s.tags,
        s.difficulty::TEXT,
        similarity(s.skill_name, search_query)::REAL as similarity_score
    FROM skills_intelligence s
    WHERE s.skill_name % search_query  -- % is the similarity operator
       OR s.description % search_query
    ORDER BY similarity_score DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;
