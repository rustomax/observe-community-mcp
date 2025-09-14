-- Datasets Intelligence Schema
-- Fast dataset discovery using PostgreSQL full-text search
-- This replaces the embeddings-based semantic graph approach with rule-based analysis

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Drop old table if exists
DROP TABLE IF EXISTS dataset_intelligence CASCADE;

-- Main datasets intelligence table
CREATE TABLE IF NOT EXISTS datasets_intelligence (
    -- Identity
    dataset_id VARCHAR(255) PRIMARY KEY,
    dataset_name VARCHAR(500) NOT NULL,
    dataset_type VARCHAR(50) NOT NULL, -- Event, Interval, Resource
    workspace_id VARCHAR(255),
    
    -- Interfaces and structure
    interface_types TEXT[], -- ['log', 'metric', 'otel_span']
    
    -- Categorization (rule-based)
    business_categories JSONB NOT NULL DEFAULT '[]'::jsonb, -- Array of categories: ["Infrastructure", "Application", "Database", etc.]
    technical_category VARCHAR(50) NOT NULL, -- Logs, Metrics, Traces, Events, Resources
    
    -- Analysis fields
    inferred_purpose TEXT NOT NULL,
    typical_usage TEXT NOT NULL,
    
    -- Key schema information
    key_fields TEXT[], -- Important field names for investigations
    sample_data_summary TEXT, -- Brief summary of sample data patterns

    -- Query assistance (enhanced with nested field support)
    query_patterns JSONB, -- Multiple OPAL query patterns: [{"pattern": "...", "description": "...", "use_case": "..."}]
    nested_field_paths JSONB, -- Important nested field paths: {"field_path": {"frequency": 0.8, "sample_values": [...], "cardinality": 50}}
    nested_field_analysis JSONB, -- Analysis of nested fields: {"important_fields": [...], "field_types": {...}, "max_depth": 3}
    
    -- Usage patterns
    common_use_cases TEXT[], -- Array of common investigation scenarios
    data_frequency VARCHAR(20), -- high, medium, low
    
    -- Metadata
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    excluded BOOLEAN DEFAULT FALSE,
    exclusion_reason VARCHAR(100),
    confidence_score REAL DEFAULT 1.0,
    last_analyzed TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Full-text search (key feature!)
    search_vector TSVECTOR
);

-- Indexes for fast searching
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_search ON datasets_intelligence USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_category ON datasets_intelligence USING gin (business_categories);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_type ON datasets_intelligence (dataset_type);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_interfaces ON datasets_intelligence USING GIN (interface_types);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_excluded ON datasets_intelligence (excluded) WHERE excluded = FALSE;

-- Trigram indexes for similarity matching (fuzzy search)
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_name_trgm ON datasets_intelligence USING GIN (dataset_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_purpose_trgm ON datasets_intelligence USING GIN (inferred_purpose gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_usage_trgm ON datasets_intelligence USING GIN (typical_usage gin_trgm_ops);

-- Drop existing functions to avoid return type conflicts
DROP FUNCTION IF EXISTS search_datasets(text,integer,text,text,text);

-- Fast search function
CREATE OR REPLACE FUNCTION search_datasets(
    search_query TEXT,
    max_results INTEGER DEFAULT 20,
    business_category_filter TEXT DEFAULT NULL,
    technical_category_filter TEXT DEFAULT NULL,
    interface_filter TEXT DEFAULT NULL
)
RETURNS TABLE (
    dataset_id TEXT,
    dataset_name TEXT,
    inferred_purpose TEXT,
    typical_usage TEXT,
    business_categories JSONB,
    technical_category TEXT,
    interface_types TEXT[],
    key_fields TEXT[],
    query_patterns JSONB,
    nested_field_paths JSONB,
    nested_field_analysis JSONB,
    common_use_cases TEXT[],
    data_frequency TEXT,
    rank REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        di.dataset_id::TEXT,
        di.dataset_name::TEXT,
        di.inferred_purpose,
        di.typical_usage,
        di.business_categories,
        di.technical_category::TEXT,
        di.interface_types,
        di.key_fields,
        di.query_patterns,
        di.nested_field_paths,
        di.nested_field_analysis,
        di.common_use_cases,
        di.data_frequency::TEXT,
        ts_rank(di.search_vector, plainto_tsquery('english', search_query)) AS rank
    FROM datasets_intelligence di
    WHERE 
        excluded = FALSE
        AND di.search_vector @@ plainto_tsquery('english', search_query)
        AND (business_category_filter IS NULL OR di.business_categories ? business_category_filter)
        AND (technical_category_filter IS NULL OR di.technical_category = technical_category_filter)
        AND (interface_filter IS NULL OR interface_filter = ANY(di.interface_types))
    ORDER BY 
        ts_rank(di.search_vector, plainto_tsquery('english', search_query)) DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Drop existing enhanced function to avoid return type conflicts
DROP FUNCTION IF EXISTS search_datasets_enhanced(text,integer,text,text,text,real);

-- Enhanced search function with trigram similarity
CREATE OR REPLACE FUNCTION search_datasets_enhanced(
    search_query TEXT,
    max_results INTEGER DEFAULT 20,
    business_category_filter TEXT DEFAULT NULL,
    technical_category_filter TEXT DEFAULT NULL,
    interface_filter TEXT DEFAULT NULL,
    similarity_threshold REAL DEFAULT 0.2
)
RETURNS TABLE (
    dataset_id TEXT,
    dataset_name TEXT,
    inferred_purpose TEXT,
    typical_usage TEXT,
    business_categories JSONB,
    technical_category TEXT,
    interface_types TEXT[],
    key_fields TEXT[],
    query_patterns JSONB,
    nested_field_paths JSONB,
    nested_field_analysis JSONB,
    common_use_cases TEXT[],
    data_frequency TEXT,
    rank REAL,
    similarity_score REAL
) AS $$
DECLARE
    cleaned_query TEXT;
BEGIN
    -- Clean and normalize query
    cleaned_query := unaccent(lower(trim(search_query)));

    RETURN QUERY
    WITH fulltext_results AS (
        SELECT
            di.dataset_id::TEXT,
            di.dataset_name::TEXT,
            di.inferred_purpose,
            di.typical_usage,
            di.business_categories,
            di.technical_category::TEXT,
            di.interface_types,
            di.key_fields,
            di.query_patterns,
            di.nested_field_paths,
            di.nested_field_analysis,
            di.common_use_cases,
            di.data_frequency::TEXT,
            ts_rank(di.search_vector, plainto_tsquery('english', search_query)) AS rank,
            0.0::REAL AS similarity_score
        FROM datasets_intelligence di
        WHERE
            excluded = FALSE
            AND di.search_vector @@ plainto_tsquery('english', search_query)
            AND (business_category_filter IS NULL OR di.business_categories ? business_category_filter)
            AND (technical_category_filter IS NULL OR di.technical_category = technical_category_filter)
            AND (interface_filter IS NULL OR interface_filter = ANY(di.interface_types))
    ),
    similarity_results AS (
        SELECT
            di.dataset_id::TEXT,
            di.dataset_name::TEXT,
            di.inferred_purpose,
            di.typical_usage,
            di.business_categories,
            di.technical_category::TEXT,
            di.interface_types,
            di.key_fields,
            di.query_patterns,
            di.nested_field_paths,
            di.nested_field_analysis,
            di.common_use_cases,
            di.data_frequency::TEXT,
            0.0::REAL AS rank,
            GREATEST(
                similarity(unaccent(lower(di.dataset_name)), cleaned_query),
                similarity(unaccent(lower(di.inferred_purpose)), cleaned_query),
                similarity(unaccent(lower(di.typical_usage)), cleaned_query)
            ) AS similarity_score
        FROM datasets_intelligence di
        WHERE
            excluded = FALSE
            AND (business_category_filter IS NULL OR di.business_categories ? business_category_filter)
            AND (technical_category_filter IS NULL OR di.technical_category = technical_category_filter)
            AND (interface_filter IS NULL OR interface_filter = ANY(di.interface_types))
            AND (
                similarity(unaccent(lower(di.dataset_name)), cleaned_query) > similarity_threshold
                OR similarity(unaccent(lower(di.inferred_purpose)), cleaned_query) > similarity_threshold
                OR similarity(unaccent(lower(di.typical_usage)), cleaned_query) > similarity_threshold
            )
    ),
    combined_results AS (
        SELECT * FROM fulltext_results
        UNION
        SELECT * FROM similarity_results
    )
    SELECT
        cr.dataset_id,
        cr.dataset_name,
        cr.inferred_purpose,
        cr.business_categories,
        cr.technical_category,
        cr.interface_types,
        cr.rank,
        cr.similarity_score
    FROM combined_results cr
    ORDER BY
        -- Prioritize full-text matches, then similarity
        (CASE WHEN cr.rank > 0 THEN cr.rank ELSE cr.similarity_score * 0.5 END) DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Search vector trigger function
CREATE OR REPLACE FUNCTION update_datasets_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector = 
        setweight(to_tsvector('english', COALESCE(NEW.dataset_name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.inferred_purpose, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.typical_usage, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(ARRAY(SELECT jsonb_array_elements_text(NEW.business_categories)), ' '), '') || ' ' || COALESCE(NEW.technical_category, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.interface_types, ' '), '')), 'D') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.common_use_cases, ' '), '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Update trigger for updated_at
CREATE OR REPLACE FUNCTION update_datasets_intelligence_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers (drop first to avoid conflicts)
DROP TRIGGER IF EXISTS datasets_intelligence_search_vector ON datasets_intelligence;
DROP TRIGGER IF EXISTS datasets_intelligence_updated_at ON datasets_intelligence;

CREATE TRIGGER datasets_intelligence_search_vector
    BEFORE INSERT OR UPDATE ON datasets_intelligence
    FOR EACH ROW
    EXECUTE FUNCTION update_datasets_search_vector();

CREATE TRIGGER datasets_intelligence_updated_at
    BEFORE UPDATE ON datasets_intelligence
    FOR EACH ROW
    EXECUTE FUNCTION update_datasets_intelligence_updated_at();

-- Convenience views for common queries
CREATE OR REPLACE VIEW datasets_by_category AS
SELECT
    jsonb_array_elements_text(business_categories) as business_category,
    technical_category,
    COUNT(*) as dataset_count,
    array_agg(DISTINCT dataset_type) as types,
    array_agg(dataset_name ORDER BY dataset_name) as datasets
FROM datasets_intelligence
WHERE excluded = FALSE
GROUP BY jsonb_array_elements_text(business_categories), technical_category
ORDER BY business_category, technical_category;

CREATE OR REPLACE VIEW datasets_by_interface AS
SELECT 
    UNNEST(interface_types) as interface_type,
    COUNT(*) as dataset_count,
    array_agg(dataset_name ORDER BY dataset_name) as datasets
FROM datasets_intelligence 
WHERE excluded = FALSE AND interface_types IS NOT NULL
GROUP BY UNNEST(interface_types)
ORDER BY COUNT(*) DESC;