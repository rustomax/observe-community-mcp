# Observe Community MCP Server

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.95+-009688?style=flat-square&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-BM25-336791?style=flat-square&logo=postgresql&logoColor=white)
![Model Context Protocol](https://img.shields.io/badge/MCP-Compatible-6366F1?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEyIDJMMTMuMDkgOC4yNkwyMCA5TDEzLjA5IDE1Ljc0TDEyIDIyTDEwLjkxIDE1Ljc0TDQgOUwxMC45MSA4LjI2TDEyIDJaIiBmaWxsPSJ3aGl0ZSIvPgo8L3N2Zz4K&logoColor=white)
![Observe](https://img.shields.io/badge/Observe-Platform-FF8C00?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KY2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSI4IiBmaWxsPSJ3aGl0ZSIvPgo8L3N2Zz4=&logoColor=white)

A Model Context Protocol (MCP) server that provides LLMs with intelligent access to [Observe](https://observeinc.com) platform data through semantic search, automated dataset discovery, and metrics intelligence.

## What This Does

This MCP server transforms how LLMs interact with observability data by providing intelligent discovery and search capabilities for the Observe platform. Instead of requiring users to know specific dataset names or metric structures, it enables natural language queries that automatically find relevant data sources and provide contextual analysis.

**Key Features:**
- **Smart Dataset Discovery**: Find relevant datasets using natural language descriptions
- **Metrics Intelligence**: Discover and understand metrics with automated categorization and usage guidance
- **Documentation Search**: Fast BM25-powered search through Observe documentation and OPAL reference
- **OPAL Query Execution**: Run queries against any Observe dataset with multi-dataset join support
- **Zero External Dependencies**: Self-contained with PostgreSQL BM25 search (no Pinecone/OpenAI required)

> **⚠️ EXPERIMENTAL**: This is a community-built MCP server for testing and collaboration. A production version is available to Observe customers through official channels.

## Table of Contents

- [Available Tools](#available-tools)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Intelligence Systems](#intelligence-systems)
- [Authentication](#authentication)
- [Usage Examples](#usage-examples)
- [Maintenance](#maintenance)

## Available Tools

The server provides 6 intelligent tools for Observe platform interaction:

### 📊 Dataset & Metrics Discovery
- **`discover_datasets`**: Find datasets using natural language queries with intelligent categorization and usage examples
- **`discover_metrics`**: Search through 500+ analyzed metrics with business/technical categorization and relevance scoring
- **`list_datasets`**: List available datasets with filtering options (direct Observe API)
- **`get_dataset_info`**: Get detailed schema information for specific datasets (direct Observe API)

### 🔍 Query & Search
- **`execute_opal_query`**: Run OPAL queries against single or multiple Observe datasets with comprehensive error handling
- **`get_relevant_docs`**: Search Observe documentation and OPAL language reference using fast PostgreSQL BM25 search

### 🤖 System Integration
- **`get_system_prompt`**: Retrieve the system prompt that configures LLMs as Observe platform experts

Each tool includes authentication validation, error handling, and structured result formatting optimized for LLM consumption.

## Quick Start

### Prerequisites

- **Docker & Docker Compose** (recommended approach)
- **Python 3.11+** (for manual installation)
- **Observe API credentials** (customer ID and token)

### 1. Clone and Configure

```bash
git clone https://github.com/your-repo/observe-community-mcp.git
cd observe-community-mcp

# Copy and configure environment
cp .env.template .env
# Edit .env with your Observe credentials (see below)
```

### 2. Environment Configuration

Edit your `.env` file with these required values:

```bash
# Observe Platform Access
OBSERVE_CUSTOMER_ID="your_customer_id"
OBSERVE_TOKEN="your_api_token"
OBSERVE_DOMAIN="observeinc.com"

# MCP Authentication (see Authentication section)
PUBLIC_KEY_PEM="-----BEGIN PUBLIC KEY-----
your_public_key_content_here
-----END PUBLIC KEY-----"

# Database Security
SEMANTIC_GRAPH_PASSWORD="your_secure_postgres_password"
```

### 3. Start with Docker (Recommended)

```bash
# Build and start all services
docker-compose up --build

# The server will be available at http://localhost:8000
```

### 4. Initialize Intelligence Systems

```bash
# Populate documentation search index
docker exec observe-mcp-server python scripts/setup_bm25_docs.py

# Build dataset and metrics intelligence (takes 5-10 minutes)
docker exec observe-mcp-server python scripts/datasets_intelligence.py
docker exec observe-mcp-server python scripts/metrics_intelligence.py
```

### 5. Connect with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "observe-community": {
      "command": "npx",
      "args": [
        "mcp-remote@latest",
        "http://localhost:8000/sse",
        "--header", "Authorization: Bearer your_mcp_token_here"
      ]
    }
  }
}
```

## Architecture

The MCP server uses a modern, self-contained architecture built for performance and reliability:

### Core Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| **MCP Server** | FastAPI + MCP Protocol | Tool definitions and request handling |
| **Observe Integration** | Python asyncio + Observe API | Dataset queries and metadata access |
| **Search Engine** | PostgreSQL + ParadeDB BM25 | Fast documentation and content search |
| **Intelligence Systems** | PostgreSQL + Rule-based Analysis | Dataset and metrics discovery with categorization |
| **Authentication** | JWT + RSA signatures | Secure access control |

### Data Flow

```
Claude/LLM Request
    ↓
MCP Server (FastAPI)
    ↓
Intelligence Layer (PostgreSQL)
    ↓
Observe Platform (OPAL Queries)
    ↓
Structured Results → LLM
```

### Database Schema

**PostgreSQL with Extensions:**
- `pg_search` (ParadeDB BM25) - Fast full-text search
- Standard PostgreSQL - Metadata storage and analysis

**Key Tables:**
- `datasets_intelligence` - Analyzed dataset metadata with categories and usage patterns
- `metrics_intelligence` - 500+ metrics with business/technical categorization
- `documentation_chunks` - Searchable documentation content with BM25 indexing

## Intelligence Systems

### Dataset Intelligence

Automatically categorizes and analyzes all Observe datasets to enable natural language discovery:

**Categories:**
- **Business**: Application, Infrastructure, Database, User, Security, Network
- **Technical**: Logs, Metrics, Traces, Events, Resources
- **Usage Patterns**: Common query examples, grouping suggestions, typical use cases

**Example Query:** *"Find kubernetes error logs"* → Automatically discovers and ranks Kubernetes log datasets

### Metrics Intelligence

Analyzes 500+ metrics from Observe with comprehensive metadata:

**Analysis Includes:**
- **Categorization**: Business domain (Infrastructure/Application/Database) + Technical type (Error/Latency/Performance)
- **Dimensions**: Common grouping fields with cardinality analysis
- **Usage Guidance**: Typical aggregation functions, alerting patterns, troubleshooting approaches
- **Value Analysis**: Data ranges, frequencies, and patterns

**Example Query:** *"CPU memory utilization metrics"* → Returns relevant infrastructure performance metrics with usage guidance

### Documentation Search

Fast BM25 full-text search through:
- Complete OPAL language reference
- Observe platform documentation
- Query examples and troubleshooting guides

**Search Features:**
- Relevance scoring with BM25 algorithm
- Context-aware chunk retrieval
- No external API dependencies

## Authentication

### MCP Server Authentication

The server uses JWT-based authentication to control access:

```bash
# Generate RSA key pair
openssl genrsa -out private_key.pem 2048
openssl rsa -in private_key.pem -pubout -out public_key.pem

# Add public key to .env file
cat public_key.pem  # Copy to PUBLIC_KEY_PEM

# Generate user tokens
./scripts/generate_mcp_token.sh 'user@example.com' 'admin,read,write' '4H'
```

### Observe API Access

**Important Security Note**: Once authenticated to the MCP server, users assume the identity and permissions of the Observe API token configured in the environment. Use Observe RBAC to limit the token's permissions appropriately.

## Usage Examples

### Dataset Discovery
```
User: "Find datasets with Kubernetes pod logs"
→ Returns ranked list of Kubernetes log datasets with usage examples
```

### Metrics Search
```
User: "Show me HTTP error rate metrics"
→ Finds relevant HTTP request/error metrics with categorization and query suggestions
```

### Documentation Search
```
User: "How do I use OPAL filter syntax?"
→ Returns relevant documentation sections with examples
```

### Multi-Dataset Queries
```
User: "Join service metrics with trace data"
→ Provides guidance and executes complex multi-dataset OPAL queries
```

## Maintenance

### Update Intelligence Data

```bash
# Refresh dataset intelligence (when new datasets are added)
docker exec observe-mcp-server python scripts/datasets_intelligence.py --force

# Update metrics intelligence (daily recommended)
docker exec observe-mcp-server python scripts/metrics_intelligence.py --force

# Rebuild documentation index (when docs change)
docker exec observe-mcp-server python scripts/setup_bm25_docs.py --force
```

### Monitor Performance

```bash
# Check server logs
docker logs observe-mcp-server

# Check database status
docker exec observe-semantic-graph psql -U semantic_graph -d semantic_graph -c "\dt"

# Check search performance
docker logs observe-mcp-server | grep "docs search"
```

### Troubleshooting

**Common Issues:**

1. **Empty search results**: Run intelligence scripts to populate data
2. **Slow performance**: Check PostgreSQL connection and restart if needed
3. **Authentication failures**: Verify JWT token and public key configuration
4. **Missing datasets**: Confirm Observe API credentials and network access

**Performance Optimization:**

The system is designed for fast response times:
- Dataset discovery: < 2 seconds
- Metrics search: < 1 second
- Documentation search: < 500ms
- Intelligence updates: Run overnight or when data changes

---

## Development

### Manual Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL (separate terminal)
docker run --name observe-postgres -p 5432:5432 -e POSTGRES_PASSWORD=yourpassword paradedb/paradedb:latest

# Initialize and run server
python scripts/setup_bm25_docs.py
python scripts/datasets_intelligence.py
python scripts/metrics_intelligence.py
python observe_server.py
```

### Contributing

This project demonstrates modern approaches to LLM-native observability tooling. Issues, feature requests, and pull requests are welcome.

**Architecture Principles:**
- Self-contained (minimal external dependencies)
- Fast (< 2 second response times)
- Intelligent (automated categorization and discovery)
- Reliable (comprehensive error handling)