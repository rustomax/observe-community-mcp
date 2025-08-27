# Observe Community MCP Server

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.95+-009688?style=flat-square&logo=fastapi&logoColor=white)
![Pinecone](https://img.shields.io/badge/Pinecone-Vector_Search-FF6C37?style=flat-square&logo=pinecone&logoColor=white)
![Model Context Protocol](https://img.shields.io/badge/MCP-Compatible-6366F1?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEyIDJMMTMuMDkgOC4yNkwyMCA5TDEzLjA5IDE1Ljc0TDEyIDIyTDEwLjkxIDE1Ljc0TDQgOUwxMC45MSA4LjI2TDEyIDJaIiBmaWxsPSJ3aGl0ZSIvPgo8L3N2Zz4K&logoColor=white)
![Observe](https://img.shields.io/badge/Observe-Platform-FF8C00?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KY2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSI4IiBmaWxsPSJ3aGl0ZSIvPgo8L3N2Zz4=&logoColor=white)

A Model Context Protocol (MCP) server that provides LLMs with access to [Observe](https://observeinc.com) platform functionality through semantic search and LLM-powered dataset intelligence.

## Purpose

This MCP server enables LLMs to interact with Observe platform data through a set of 6 tools. It includes dataset discovery capabilities powered by LLM reasoning, OPAL query execution, and semantic search for documentation.

**Key capabilities:**
- Dataset discovery using LLM-powered semantic analysis
- OPAL query execution against Observe datasets
- Vector-based search for OPAL documentation and runbooks
- JWT-based authentication with role-based access control

> **⚠️ DISCLAIMER**: This is an experimental MCP server for testing and collaboration. Use at your own risk. A production-ready version, based on a completely different code base, is available to Observe customers.

## Table of Contents

- [Purpose](#purpose)
- [Available MCP Tools](#available-mcp-tools)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Setup](#environment-setup)
  - [Database Setup](#database-setup)
  - [Initialize Vector Database](#initialize-vector-database)
- [Running the Server](#running-the-server)
  - [Docker (Recommended)](#docker-recommended)
  - [Manual Python Execution](#manual-python-execution)
- [Authentication Setup](#authentication-setup)
- [Using with Claude Desktop](#using-with-claude-desktop)
- [Architecture Overview](#architecture-overview)
- [Dataset Intelligence System](#dataset-intelligence-system)
- [Maintenance](#maintenance)

## Available MCP Tools

This MCP server provides 6 core tools for Observe platform access:

### Dataset Intelligence
- **`query_semantic_graph`**: Find relevant datasets using LLM-powered analysis of query intent and dataset metadata. This uses a chached and semantically enriched dataset metadata.
- **`list_datasets`**: List available datasets with filtering options (a direct API call to Observe)
- **`get_dataset_info`**: Get detailed schema information about specific datasets (a direct API call to Observe)

### Query Execution
- **`execute_opal_query`**: Execute OPAL queries against Observe datasets with error handling and multi-dataset support (a direct API call to Observe)

### Knowledge & Documentation
- **`get_relevant_docs`**: Search Observe documentation, include OPAL language reference (semantic vector search)
- **`get_system_prompt`**: Retrieve the system prompt that configures LLMs as an Observe expert

Each tool includes error handling, authentication validation, and structured result formatting.

![Claude Desktop using Observe MCP Server](./images/claude_investigation.png)

## Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose (recommended)
- Pinecone account with API key
- Observe API credentials (customer ID and token)
- OpenAI API key (for LLM-powered dataset intelligence)

### Installation

```bash
git clone https://github.com/your-repo/observe-community-mcp.git
cd observe-community-mcp
```

### Environment Setup

Copy the example environment file and configure your credentials:

```bash
cp .env.example .env
# Edit .env with your API keys and configuration
```

Required variables:

```bash
# Observe Platform
OBSERVE_CUSTOMER_ID=your_customer_id
OBSERVE_TOKEN=your_api_token  
OBSERVE_DOMAIN=observeinc.com

# Vector Search (Pinecone)
PINECONE_API_KEY=your_pinecone_key
PINECONE_DOCS_INDEX=observe-docs
PINECONE_RUNBOOKS_INDEX=observe-runbooks

# LLM Intelligence (OpenAI)
OPENAI_API_KEY=your_openai_key

# Database (Dataset Intelligence)
POSTGRES_PASSWORD=secure_password

# Security
PUBLIC_KEY_PEM="-----BEGIN PUBLIC KEY-----
your_public_key_here
-----END PUBLIC KEY-----"
```

### Database Setup

The server requires a PostgreSQL database with pgvector extension for dataset intelligence functionality. This is automatically configured when using Docker Compose.

**Important**: The dataset intelligence system requires populating the database with dataset metadata before first use.

### Initialize Vector Database

Populate the Pinecone indices with documentation:

```bash
# Populate documentation index
python scripts/populate_docs_index.py

# Initialize dataset intelligence database (REQUIRED)
# This populates PostgreSQL with dataset metadata and embeddings
python scripts/populate_dataset_intelligence.py
```

> **Note**: If you don't have access to Observe documentation files, contact your Observe representative.

Options for all scripts:
- `--force`: Recreate the index from scratch
- `--verbose`: Enable detailed logging

### Runbooks

In the current iteration of the MCP server, runbooks are not supported. They were used in the previous version, and make come back in the future, so I am leaving the script to populate vector database and runbooks themselves in the repo.

## Running the Server

### Docker (Recommended)

```bash
# Start with Docker Compose
docker-compose up --build
```

The server will be available at `http://localhost:8000` with automatic health checks and PostgreSQL database.

### Manual Python Execution

For development:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Initialize database (required before first run)
python scripts/populate_dataset_intelligence.py

# Start server
python observe_server.py
```

## Authentication Setup

> **⚠️ CRITICAL: READ THIS SECTION COMPLETELY**

There are two types of authentication mechanisms used in this server:

**Observe API authentication (Observe API bearer token)** - Uses your Observe API token to access platform data. This token inherits the permissions of the user who created it.

> **⚠️ IMPORTANT**: Once a user is authenticated to the MCP server, they assume the identity of the user who generated the Observe token, not their own identity. Use RBAC and limit the Observe API token to specific roles and permissions you want available to MCP server users.

**MCP authentication (MCP bearer token)** - Controls access to the MCP server itself. This is necessary because the server exposes resource-intensive APIs (Pinecone, OpenAI).

![Authentication](./images/mcp_auth.png)

The MCP server includes basic RBAC with predefined roles: `admin`, `read`, `write`. These do not map to Observe roles and only control MCP server tool access.

### Setting up MCP Authentication

Create private and public key files:

```bash
openssl genrsa -out private_key.pem 2048
openssl rsa -in private_key.pem -pubout -out public_key.pem
```

This creates:
- `private_key.pem` - Keep this secret. Used to sign MCP bearer tokens.
- `public_key.pem` - Add to the server configuration for token verification.

Copy the public key to your `.env` file:

```bash
cat public_key.pem
# Copy output to .env as PUBLIC_KEY_PEM
```

Generate user tokens:

```bash
cd ./scripts
generate_mcp_token.sh 'user@example.com' 'admin,read,write' '4H'
```

> **Security**: Keep token expiration times short (hours rather than days).

**Local-only deployment**: If running locally without public access, you can disable MCP authentication by modifying the server configuration.

## Using with Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "observe-community": {
      "command": "npx",
      "args": [
        "mcp-remote@latest",
        "http://localhost:8000/sse",
        "--header",
        "Authorization: Bearer your_mcp_token_here"
      ]
    }
  }
}
```

> **Network Configuration Note**: MCP clients typically restrict HTTP access to localhost only. For internet-accessible deployments, implement an HTTPS reverse proxy with proper DNS configuration and SSL certificates.

The server will be available with 6 MCP tools for dataset discovery, query execution, and documentation search.

![Claude Desktop using Observe MCP Server](./images/claude_tools.png)

## Architecture Overview

The MCP server uses a modular architecture:

| Component | Purpose |
|-----------|---------| 
| `observe_server.py` | Main MCP server with 6 tool definitions |
| `src/observe/` | Observe API integration (queries, datasets, client) |
| `src/dataset_intelligence/` | LLM-powered dataset discovery with PostgreSQL + pgvector |
| `src/pinecone/` | Vector database operations for documentation search |
| `src/auth/` | JWT authentication and scope-based authorization |
| `scripts/` | Database population and maintenance scripts |

**Technology Stack:**
- **MCP Server**: FastAPI + MCP Protocol
- **Dataset Intelligence**: PostgreSQL + pgvector + OpenAI GPT-4
- **Query Engine**: Python asyncio + Observe API
- **Vector Search**: Pinecone + OpenAI embeddings
- **Authentication**: JWT + RSA keys
- **Caching**: PostgreSQL-based dataset metadata caching

## Dataset Semantic Search System

The dataset semantic search system uses LLM reasoning to understand user queries and match them with relevant Observe datasets.

### How It Works

1. **Query Analysis**: Analyzes user queries to detect explicit dataset mentions, domain keywords, and intent
2. **Candidate Selection**: Retrieves relevant datasets from PostgreSQL cache with smart sampling
3. **LLM Ranking**: Uses GPT-4 to rank datasets based on relevance with detailed explanations  
4. **Result Enhancement**: Applies quality filters and diversity balancing

### Key Features

**Explicit Dataset Detection**: Recognizes when users mention specific datasets by name
```
"Give me k8s logs" → Kubernetes Explorer/Kubernetes Logs (prioritized)
"Show me span data" → OpenTelemetry/Span (prioritized)
```

**Domain Intelligence**: Maps query domains to appropriate dataset types
```
"database performance" → Database Call datasets
"trace analysis" → OpenTelemetry/Span datasets  
"error investigation" → Log datasets + Error spans
```

**Smart Prioritization**: Applies observability expertise
- OpenTelemetry/Span always ranks first for trace/performance queries
- Log datasets prioritized for debugging/error queries
- Database datasets top-ranked for SQL/performance queries

### Performance

The system provides dataset recommendations typically within 1-3 seconds, with high accuracy for domain-specific queries. It maintains a local cache of dataset metadata in PostgreSQL for performance.

## Maintenance

### Update Vector Databases

```bash
# Update documentation index
python scripts/populate_docs_index.py --force

# Update runbooks index  
python scripts/populate_runbooks_index.py --force

# Update dataset intelligence cache
python scripts/populate_dataset_intelligence.py --force
```

### Monitor Performance

```bash
# Check logs for performance metrics
docker logs observe-mcp-server | grep "[SEMANTIC_GRAPH]"

# Check database status
docker exec observe-opal-memory psql -U opal -d opal_memory -c "\dt"
```

### Common Issues

1. **No dataset recommendations**: Verify OpenAI API key and database population
2. **Slow responses**: Check PostgreSQL connection and dataset cache
3. **Authentication errors**: Validate JWT token and public key configuration
4. **Missing documentation**: Run populate scripts with `--force` flag

All scripts support `--force` to recreate indices and `--verbose` for detailed logging.

---

> **Contributing**: Issues, feature requests, and pull requests are welcome. This project demonstrates LLM-native observability tooling approaches.