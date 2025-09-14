-- Metrics Intelligence Table for Fast Text Search and Discovery
-- This table stores detailed information about individual metrics within datasets
-- Extends the dataset_intelligence table with metrics-specific information

-- Drop existing table to recreate with new schema
DROP TABLE IF EXISTS metrics_intelligence CASCADE;

CREATE TABLE metrics_intelligence (
    -- Metric identification (unique per dataset + metric name combination)
    id SERIAL PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    
    -- Dataset context (denormalized for performance)
    dataset_name TEXT NOT NULL,
    dataset_type TEXT NOT NULL,
    workspace_id TEXT,
    
    -- Metric-specific information
    metric_type TEXT,                    -- counter, gauge, histogram, summary (from OpenTelemetry)
    unit TEXT,                          -- seconds, bytes, requests/sec, etc.
    description TEXT,                   -- Metric description when available
    
    -- Dimensional analysis
    common_dimensions JSONB,            -- Most frequently occurring label/tag keys
    dimension_cardinality JSONB,       -- Cardinality of each dimension (approx)
    sample_dimensions JSONB,            -- Sample dimension values for context
    
    -- Value analysis
    value_type TEXT,                    -- float, integer, boolean
    value_range JSONB,                  -- {min: x, max: y, avg: z} from samples
    sample_values NUMERIC[],            -- Sample values for context
    
    -- Usage patterns
    data_frequency TEXT,                -- high, medium, low based on data points
    last_seen TIMESTAMP,               -- When this metric was last observed
    first_seen TIMESTAMP,              -- When this metric was first observed
    
    -- LLM-generated intelligence
    inferred_purpose TEXT,             -- What this metric measures (LLM analysis)
    typical_usage TEXT,                -- Investigation scenarios for this specific metric
    business_categories JSONB NOT NULL DEFAULT '[]'::jsonb, -- Multiple categories: ["Infrastructure", "Application"], etc.
    technical_category TEXT,           -- Performance, Error, Resource, Business, etc.
    
    -- Query assistance (enhanced with nested field support)
    query_patterns JSONB,              -- DEPRECATED: Multiple OPAL query patterns (no longer populated)
    common_fields TEXT[],              -- Common field names available for grouping
    nested_field_paths JSONB,          -- Important nested field paths: {"field_path": {"frequency": 0.8, "sample_values": [...], "cardinality": 50}}
    nested_field_analysis JSONB,       -- Analysis of nested fields: {"important_fields": [...], "field_types": {...}, "max_depth": 3}
    
    -- Full-text search vectors for fast text search
    search_vector TSVECTOR,             -- Searchable text: metric name, description, purpose, dimensions
    
    -- Metadata
    excluded BOOLEAN DEFAULT FALSE,     -- Whether to exclude from search results
    exclusion_reason TEXT,             -- Why excluded (internal metric, etc.)
    confidence_score FLOAT DEFAULT 1.0, -- Confidence in the analysis (0-1)
    
    -- Tracking
    last_analyzed TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Ensure uniqueness per dataset + metric
    UNIQUE(dataset_id, metric_name)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_dataset ON metrics_intelligence(dataset_id);
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_name ON metrics_intelligence(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_type ON metrics_intelligence(metric_type);
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_category ON metrics_intelligence USING GIN(business_categories);
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_excluded ON metrics_intelligence(excluded) WHERE excluded = FALSE;
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_last_seen ON metrics_intelligence(last_seen DESC);

-- Full-text search index for fast metric discovery
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_search_vector
ON metrics_intelligence USING gin(search_vector);

-- Trigram indexes for similarity matching (fuzzy search)
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_name_trgm ON metrics_intelligence USING GIN (metric_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_purpose_trgm ON metrics_intelligence USING GIN (inferred_purpose gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_metrics_intelligence_usage_trgm ON metrics_intelligence USING GIN (typical_usage gin_trgm_ops);

-- Trigger to automatically update search vector when data changes
CREATE OR REPLACE FUNCTION update_metrics_search_vector() RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := 
        setweight(to_tsvector('english', COALESCE(NEW.metric_name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.description, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.inferred_purpose, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.typical_usage, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(ARRAY(SELECT jsonb_array_elements_text(NEW.business_categories)), ' '), '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(NEW.technical_category, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(
            (SELECT string_agg(key, ' ') FROM jsonb_object_keys(NEW.common_dimensions) AS key), '')), 'D');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_metrics_search_vector
    BEFORE INSERT OR UPDATE ON metrics_intelligence
    FOR EACH ROW EXECUTE FUNCTION update_metrics_search_vector();

-- Helper views
CREATE OR REPLACE VIEW active_metrics AS 
SELECT * FROM metrics_intelligence WHERE excluded = FALSE;

CREATE OR REPLACE VIEW metrics_by_dataset AS
SELECT 
    dataset_id,
    dataset_name,
    COUNT(*) as metric_count,
    COUNT(*) FILTER (WHERE excluded = FALSE) as active_metric_count,
    ARRAY_AGG(DISTINCT metric_type) FILTER (WHERE metric_type IS NOT NULL) as metric_types,
    ARRAY_AGG(DISTINCT cat) FILTER (WHERE cat IS NOT NULL) as categories
FROM metrics_intelligence,
     LATERAL jsonb_array_elements_text(business_categories) AS cat
GROUP BY dataset_id, dataset_name;

-- Summary view for quick overview
CREATE OR REPLACE VIEW metrics_summary AS
SELECT
    jsonb_array_elements_text(business_categories) as business_category,
    technical_category,
    COUNT(*) as metric_count,
    COUNT(DISTINCT dataset_id) as dataset_count,
    AVG(confidence_score) as avg_confidence
FROM metrics_intelligence
WHERE excluded = FALSE
GROUP BY jsonb_array_elements_text(business_categories), technical_category
ORDER BY metric_count DESC;

-- Drop existing functions to avoid return type conflicts
DROP FUNCTION IF EXISTS search_metrics(text,integer);
DROP FUNCTION IF EXISTS search_metrics_enhanced(text,integer,text,text,real);

-- Search function for metrics using full-text search
CREATE OR REPLACE FUNCTION search_metrics(search_query TEXT, max_results INT DEFAULT 20)
RETURNS TABLE (
    metric_name TEXT,
    dataset_name TEXT,
    description TEXT,
    inferred_purpose TEXT,
    business_categories JSONB,
    technical_category TEXT,
    rank REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        m.metric_name,
        m.dataset_name,
        m.description,
        m.inferred_purpose,
        m.business_categories,
        m.technical_category,
        ts_rank(m.search_vector, plainto_tsquery('english', search_query)) AS rank
    FROM metrics_intelligence m
    WHERE 
        m.excluded = FALSE
        AND m.search_vector @@ plainto_tsquery('english', search_query)
    ORDER BY rank DESC, m.metric_name
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Drop existing functions to avoid return type conflicts
DROP FUNCTION IF EXISTS search_metrics_enhanced(text,integer,text,text,real);

-- Enhanced search function with trigram similarity for metrics
CREATE OR REPLACE FUNCTION search_metrics_enhanced(
    search_query TEXT,
    max_results INTEGER DEFAULT 20,
    category_filter TEXT DEFAULT NULL,
    technical_filter TEXT DEFAULT NULL,
    similarity_threshold REAL DEFAULT 0.2
)
RETURNS TABLE (
    metric_name TEXT,
    dataset_name TEXT,
    inferred_purpose TEXT,
    typical_usage TEXT,
    business_categories JSONB,
    technical_category TEXT,
    metric_type TEXT,
    common_fields TEXT[],
    nested_field_paths JSONB,
    nested_field_analysis JSONB,
    common_dimensions JSONB,
    value_range JSONB,
    data_frequency TEXT,
    last_seen TIMESTAMP,
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
            m.metric_name,
            m.dataset_name,
            m.inferred_purpose,
            m.typical_usage,
            m.business_categories,
            m.technical_category,
            m.metric_type,
            m.common_fields,
            m.nested_field_paths,
            m.nested_field_analysis,
            m.common_dimensions,
            m.value_range,
            m.data_frequency,
            m.last_seen,
            ts_rank(m.search_vector, plainto_tsquery('english', search_query)) AS rank,
            0.0::REAL AS similarity_score
        FROM metrics_intelligence m
        WHERE
            excluded = FALSE
            AND m.search_vector @@ plainto_tsquery('english', search_query)
            AND (category_filter IS NULL OR m.business_categories ? category_filter)
            AND (technical_filter IS NULL OR m.technical_category = technical_filter)
    ),
    similarity_results AS (
        SELECT
            m.metric_name,
            m.dataset_name,
            m.inferred_purpose,
            m.typical_usage,
            m.business_categories,
            m.technical_category,
            m.metric_type,
            m.common_fields,
            m.nested_field_paths,
            m.nested_field_analysis,
            m.common_dimensions,
            m.value_range,
            m.data_frequency,
            m.last_seen,
            0.0::REAL AS rank,
            GREATEST(
                similarity(unaccent(lower(m.metric_name)), cleaned_query),
                similarity(unaccent(lower(m.inferred_purpose)), cleaned_query),
                similarity(unaccent(lower(m.typical_usage)), cleaned_query)
            ) AS similarity_score
        FROM metrics_intelligence m
        WHERE
            excluded = FALSE
            AND (category_filter IS NULL OR m.business_categories ? category_filter)
            AND (technical_filter IS NULL OR m.technical_category = technical_filter)
            AND (
                similarity(unaccent(lower(m.metric_name)), cleaned_query) > similarity_threshold
                OR similarity(unaccent(lower(m.inferred_purpose)), cleaned_query) > similarity_threshold
                OR similarity(unaccent(lower(m.typical_usage)), cleaned_query) > similarity_threshold
            )
    ),
    combined_results AS (
        SELECT * FROM fulltext_results
        UNION
        SELECT * FROM similarity_results
    )
    SELECT
        cr.metric_name,
        cr.dataset_name,
        cr.inferred_purpose,
        cr.typical_usage,
        cr.business_categories,
        cr.technical_category,
        cr.metric_type,
        cr.common_fields,
        cr.nested_field_paths,
        cr.nested_field_analysis,
        cr.common_dimensions,
        cr.value_range,
        cr.data_frequency,
        cr.last_seen,
        cr.rank,
        cr.similarity_score
    FROM combined_results cr
    ORDER BY
        -- Prioritize full-text matches, then similarity
        (CASE WHEN cr.rank > 0 THEN cr.rank ELSE cr.similarity_score * 0.5 END) DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;