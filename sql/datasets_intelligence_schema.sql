-- Datasets Intelligence Schema
-- Fast dataset discovery using PostgreSQL full-text search
-- This replaces the embeddings-based semantic graph approach with rule-based analysis

-- Enable vector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;

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
    business_category VARCHAR(50) NOT NULL, -- Infrastructure, Application, Database, etc.
    technical_category VARCHAR(50) NOT NULL, -- Logs, Metrics, Traces, Events, Resources
    
    -- Analysis fields
    inferred_purpose TEXT NOT NULL,
    typical_usage TEXT NOT NULL,
    
    -- Key schema information  
    key_fields TEXT[], -- Important field names for investigations
    sample_data_summary TEXT, -- Brief summary of sample data patterns
    
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
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_category ON datasets_intelligence (business_category, technical_category);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_type ON datasets_intelligence (dataset_type);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_interfaces ON datasets_intelligence USING GIN (interface_types);
CREATE INDEX IF NOT EXISTS idx_datasets_intelligence_excluded ON datasets_intelligence (excluded) WHERE excluded = FALSE;

-- Fast search function
CREATE OR REPLACE FUNCTION search_datasets(
    search_query TEXT,
    max_results INTEGER DEFAULT 20,
    business_category_filter TEXT DEFAULT NULL,
    technical_category_filter TEXT DEFAULT NULL,
    interface_filter TEXT DEFAULT NULL
)
RETURNS TABLE (
    dataset_id VARCHAR(255),
    dataset_name VARCHAR(500),
    inferred_purpose TEXT,
    business_category VARCHAR(50),
    technical_category VARCHAR(50),
    interface_types TEXT[],
    rank REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        di.dataset_id,
        di.dataset_name,
        di.inferred_purpose,
        di.business_category,
        di.technical_category,
        di.interface_types,
        ts_rank(di.search_vector, plainto_tsquery('english', search_query)) AS rank
    FROM datasets_intelligence di
    WHERE 
        excluded = FALSE
        AND di.search_vector @@ plainto_tsquery('english', search_query)
        AND (business_category_filter IS NULL OR di.business_category = business_category_filter)
        AND (technical_category_filter IS NULL OR di.technical_category = technical_category_filter)
        AND (interface_filter IS NULL OR interface_filter = ANY(di.interface_types))
    ORDER BY 
        ts_rank(di.search_vector, plainto_tsquery('english', search_query)) DESC
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
        setweight(to_tsvector('english', COALESCE(NEW.business_category, '') || ' ' || COALESCE(NEW.technical_category, '')), 'B') ||
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
    business_category,
    technical_category,
    COUNT(*) as dataset_count,
    array_agg(DISTINCT dataset_type) as types,
    array_agg(dataset_name ORDER BY dataset_name) as datasets
FROM datasets_intelligence 
WHERE excluded = FALSE
GROUP BY business_category, technical_category
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