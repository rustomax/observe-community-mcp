#!/bin/bash
# Skills Intelligence Setup Script
# Ensures skills search is properly configured for both fresh and existing installations

set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SQL_FILE="$PROJECT_ROOT/sql/skills_intelligence_schema.sql"

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           Skills Intelligence Setup                          ║"
echo "║  Setting up BM25 search for OPAL documentation              ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo "   Please start Docker Desktop and try again"
    exit 1
fi

echo "✓ Docker is running"

# Check if PostgreSQL container exists
if ! docker ps -a | grep -q observe-semantic-graph; then
    echo "❌ Error: PostgreSQL container not found"
    echo "   Please run: docker-compose up -d"
    exit 1
fi

echo "✓ PostgreSQL container found"

# Check if container is running
if ! docker ps | grep -q observe-semantic-graph; then
    echo "⚠️  PostgreSQL container is not running"
    echo "   Starting container..."
    docker-compose up -d postgres
    sleep 5
fi

echo "✓ PostgreSQL container is running"

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
timeout=30
counter=0
until docker exec observe-semantic-graph pg_isready -U semantic_graph -d semantic_graph > /dev/null 2>&1; do
    sleep 1
    counter=$((counter + 1))
    if [ $counter -ge $timeout ]; then
        echo "❌ Error: PostgreSQL did not become ready in time"
        exit 1
    fi
done

echo "✓ PostgreSQL is ready"

# Apply skills intelligence schema
echo "📋 Applying skills intelligence schema..."
if docker exec -i observe-semantic-graph psql -U semantic_graph -d semantic_graph < "$SQL_FILE"; then
    echo "✓ Skills intelligence schema applied successfully"
else
    echo "❌ Error: Failed to apply schema"
    exit 1
fi

# Check if pg_search extension is enabled
echo "🔍 Verifying ParadeDB pg_search extension..."
if docker exec observe-semantic-graph psql -U semantic_graph -d semantic_graph -t -c "SELECT 1 FROM pg_extension WHERE extname = 'pg_search';" | grep -q 1; then
    echo "✓ ParadeDB pg_search extension is enabled"
else
    echo "❌ Error: pg_search extension is not enabled"
    echo "   This should have been enabled by the schema"
    exit 1
fi

# Check if skills_intelligence table exists
echo "🔍 Verifying skills_intelligence table..."
if docker exec observe-semantic-graph psql -U semantic_graph -d semantic_graph -t -c "SELECT 1 FROM information_schema.tables WHERE table_name = 'skills_intelligence';" | grep -q 1; then
    echo "✓ skills_intelligence table exists"
else
    echo "❌ Error: skills_intelligence table was not created"
    exit 1
fi

# Check if BM25 index exists
echo "🔍 Verifying BM25 index..."
if docker exec observe-semantic-graph psql -U semantic_graph -d semantic_graph -t -c "SELECT 1 FROM paradedb.bm25_indexes WHERE index_name = 'skills_search_idx';" 2>/dev/null | grep -q 1; then
    echo "✓ BM25 index exists"
else
    echo "⚠️  BM25 index not found - this is expected on first run"
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  ✅ Database Setup Complete                                   ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "Next step: Load skills into database"
echo ""
echo "Run: python scripts/skills_intelligence.py --force"
echo ""
