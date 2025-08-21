-- Dataset Intelligence Table for Semantic Search and Discovery
-- This table stores rich metadata about datasets to speed up dataset discovery during investigations

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS dataset_intelligence (
    -- Dataset identification
    dataset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dataset_type TEXT NOT NULL,  -- Event, Interval, Resource
    workspace_id TEXT,
    
    -- Rich context for LLM analysis
    interfaces JSONB,            -- List of interfaces (log, metric, otel_span, etc.)
    schema_info JSONB,           -- Full schema from get_dataset_info
    sample_data JSONB,           -- Top 10 rows for context
    
    -- LLM-generated intelligence
    description TEXT,            -- What this dataset contains
    typical_usage TEXT,          -- Common investigation scenarios
    business_category TEXT,      -- Infrastructure, Application, Security, Business, etc.
    technical_category TEXT,     -- Logs, Metrics, Traces, Resources, Events
    key_fields TEXT[],           -- Most important fields for investigation
    
    -- Embeddings for semantic search
    description_embedding VECTOR(1536),  -- For purpose/use-case search
    schema_embedding VECTOR(1536),       -- For field/structure search
    combined_embedding VECTOR(1536),     -- For general search
    
    -- Metadata
    excluded BOOLEAN DEFAULT FALSE,      -- Whether to exclude from search
    exclusion_reason TEXT,              -- Why excluded (monitor, internal, etc.)
    last_analyzed TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    
    -- Performance indexes
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_dataset_intelligence_name ON dataset_intelligence(name);
CREATE INDEX IF NOT EXISTS idx_dataset_intelligence_category ON dataset_intelligence(business_category);
CREATE INDEX IF NOT EXISTS idx_dataset_intelligence_type ON dataset_intelligence(dataset_type);
CREATE INDEX IF NOT EXISTS idx_dataset_intelligence_excluded ON dataset_intelligence(excluded) WHERE excluded = FALSE;

-- Vector similarity indexes for semantic search
CREATE INDEX IF NOT EXISTS idx_dataset_intelligence_desc_embedding 
ON dataset_intelligence USING ivfflat (description_embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_dataset_intelligence_schema_embedding 
ON dataset_intelligence USING ivfflat (schema_embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_dataset_intelligence_combined_embedding 
ON dataset_intelligence USING ivfflat (combined_embedding vector_cosine_ops) WITH (lists = 100);

-- Helper view for non-excluded datasets
CREATE OR REPLACE VIEW active_datasets AS 
SELECT * FROM dataset_intelligence WHERE excluded = FALSE;