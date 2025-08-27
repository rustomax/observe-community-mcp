#!/usr/bin/env python3
"""
Observe MCP Server
A Model Context Protocol server that provides access to Observe API functionality
using organized modules for better maintainability and reusability.
"""

import os
import sys
from typing import Dict, Any, Optional, List, Union

try:
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict

# Type definitions for better type safety
class MonitorResponse(TypedDict):
    id: str
    name: str
    ruleKind: str
    description: str

class ErrorResponse(TypedDict):
    error: bool
    message: str

class SystemInfo(TypedDict):
    python_version: str
    python_path: List[str]
    environment: Dict[str, str]
    server_time: str
    server_pid: int

class AuthPermissions(TypedDict):
    admin_access: bool
    read_access: bool
    write_access: bool

class AuthTokenInfo(TypedDict):
    authenticated: bool
    client_id: str
    token_type: str
    scopes: List[str]
    permissions: AuthPermissions

# Add debugging statements to help diagnose import issues
print("Starting observe_server.py", file=sys.stderr)
print(f"Python version: {sys.version}", file=sys.stderr)
print(f"Python path: {sys.path}", file=sys.stderr)

try:
    import httpx
    from dotenv import load_dotenv
    print("Basic imports successful", file=sys.stderr)
except Exception as e:
    print(f"Error importing basic modules: {e}", file=sys.stderr)
    raise

# Try to import Pinecone and related helpers with detailed error reporting
try:
    print("Attempting to import pinecone module...", file=sys.stderr)
    import pinecone
    
    # Try to get version, but don't fail if it's not available
    try:
        version = getattr(pinecone, '__version__', 'unknown')
        print(f"Pinecone import successful. Version: {version}", file=sys.stderr)
    except (AttributeError, Exception):
        print("Pinecone import successful. Version: unknown", file=sys.stderr)
    
    # Import organized Pinecone helpers
    print("Attempting to import src.pinecone modules...", file=sys.stderr)
    from src.pinecone.search import search_docs, search_runbooks
    print("Successfully imported search functions from src.pinecone", file=sys.stderr)
except ImportError as e:
    print(f"Error importing Pinecone or helpers: {e}", file=sys.stderr)
    
    # Define fallback search functions
    def search_docs(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        print(f"FALLBACK search_docs called with query: {query}", file=sys.stderr)
        return [{
            "text": f"Error: Pinecone not available. The server cannot perform vector search because the pinecone package is not installed. Please install it with 'pip install pinecone>=3.0.0' and restart the server. Your query was: {query}", 
            "source": "error", 
            "title": "Pinecone Not Available", 
            "score": 1.0
        }]
    
    def search_runbooks(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        print(f"FALLBACK search_runbooks called with query: {query}", file=sys.stderr)
        return [{
            "text": f"Error: Pinecone not available. The server cannot perform vector search because the pinecone package is not installed. Please install it with 'pip install pinecone>=3.0.0' and restart the server. Your query was: {query}", 
            "source": "error", 
            "title": "Pinecone Not Available", 
            "score": 1.0
        }]
    
    print("Using fallback search functions", file=sys.stderr)

# Load environment variables from .env file
load_dotenv()

# Import organized Observe API modules
from src.observe import (
    list_datasets as observe_list_datasets,
    get_dataset_info as observe_get_dataset_info,
    execute_opal_query as observe_execute_opal_query
)

# Import organized auth modules
from src.auth import (
    create_authenticated_mcp,
    requires_scopes,
    initialize_auth_middleware,
    setup_auth_provider
)

# Smart tools removed - keeping only core functionality

from fastmcp import Context

# Create FastMCP instance with authentication
mcp = create_authenticated_mcp(server_name="observe-community")

# Initialize auth middleware for statistics and logging
auth_provider = setup_auth_provider()
initialize_auth_middleware(auth_provider)

# Smart tools configuration check removed

# --- MCP Tools (Refactored to use organized modules) ---

# Authentication/system tools removed - keeping only core functionality

# --- Observe API Tools (using refactored modules) ---

@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
async def execute_opal_query(ctx: Context, query: str, dataset_id: str = None, primary_dataset_id: str = None, secondary_dataset_ids: Optional[str] = None, dataset_aliases: Optional[str] = None, time_range: Optional[str] = "1h", start_time: Optional[str] = None, end_time: Optional[str] = None, row_count: Optional[int] = 1000, format: Optional[str] = "csv", timeout: Optional[float] = None) -> str:
    """
    Execute an OPAL query on single or multiple datasets.
    
    Args:
        query: The OPAL query to execute
        dataset_id: DEPRECATED: Use primary_dataset_id instead. Kept for backward compatibility.
        primary_dataset_id: The ID of the primary dataset to query
        secondary_dataset_ids: Optional JSON string list of secondary dataset IDs (e.g., '["44508111"]')
        dataset_aliases: Optional JSON string mapping of aliases to dataset IDs (e.g., '{"volumes": "44508111"}')
        time_range: Time range for the query (e.g., "1h", "1d", "7d"). Used if start_time and end_time are not provided.
        start_time: Optional start time in ISO format (e.g., "2023-04-20T16:20:00Z")
        end_time: Optional end time in ISO format (e.g., "2023-04-20T16:30:00Z")
        row_count: Maximum number of rows to return (default: 1000, max: 100000)
        format: Output format, either "csv" or "ndjson" (default: "csv")
        timeout: Request timeout in seconds (default: uses client default of 30s)
    
    Examples:
        # Single dataset query (backward compatible)
        execute_opal_query(query="filter metric = 'CPUUtilization'", dataset_id="44508123")
        
        # Multi-dataset join query
        execute_opal_query(
            query="join on(instanceId=@volumes.instanceId), volume_size:@volumes.size",
            primary_dataset_id="44508123",  # EC2 Instance Metrics
            secondary_dataset_ids='["44508111"]',  # EBS Volumes (JSON string)
            dataset_aliases='{"volumes": "44508111"}'  # Aliases (JSON string)
        )
    """
    import json
    
    # Parse JSON string parameters if provided
    parsed_secondary_dataset_ids = None
    parsed_dataset_aliases = None
    
    if secondary_dataset_ids:
        try:
            parsed_secondary_dataset_ids = json.loads(secondary_dataset_ids)
        except (json.JSONDecodeError, TypeError) as e:
            return f"Error parsing secondary_dataset_ids: {e}. Expected JSON array like ['44508111']"
    
    if dataset_aliases:
        try:
            parsed_dataset_aliases = json.loads(dataset_aliases)
        except (json.JSONDecodeError, TypeError) as e:
            return f"Error parsing dataset_aliases: {e}. Expected JSON object like {{\"volumes\": \"44508111\"}}"
    
    return await observe_execute_opal_query(
        query=query,
        dataset_id=dataset_id,
        primary_dataset_id=primary_dataset_id,
        secondary_dataset_ids=parsed_secondary_dataset_ids,
        dataset_aliases=parsed_dataset_aliases,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time,
        row_count=row_count,
        format=format,
        timeout=timeout
    )

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def list_datasets(ctx: Context, match: Optional[str] = None, workspace_id: Optional[str] = None, type: Optional[str] = None, interface: Optional[str] = None) -> str:
    """
    List available datasets in Observe.
    
    Args:
        match: Optional substring to match dataset names
        workspace_id: Optional workspace ID to filter by
        type: Optional dataset type to filter by (e.g., 'Event')
        interface: Optional interface to filter by (e.g., 'metric', 'log')
    """
    return await observe_list_datasets(
        match=match,
        workspace_id=workspace_id,
        type=type,
        interface=interface
    )

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def get_dataset_info(ctx: Context, dataset_id: str) -> str:
    """
    Get detailed information about a specific dataset.
    
    Args:
        dataset_id: The ID of the dataset
    """
    return await observe_get_dataset_info(dataset_id=dataset_id)

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def get_relevant_docs(ctx: Context, query: str, n_results: int = 5) -> str:
    """Get relevant documentation for a query using Pinecone vector search"""
    try:
        # Import required modules
        import os
        from collections import defaultdict
        
        print(f"Searching for relevant docs using Pinecone: {query}", file=sys.stderr)
        chunk_results = search_docs(query, n_results=max(n_results * 3, 15))  # Get more chunks to ensure we have enough from relevant docs
        
        if not chunk_results:
            print(f"No relevant documents found for: '{query}'", file=sys.stderr)
            return f"No relevant documents found for: '{query}'"
        
        # Group chunks by source document
        docs_by_source = defaultdict(list)
        for result in chunk_results:
            source = result.get("source", "")
            if source and source != "error":
                docs_by_source[source].append(result)
        
        # Calculate average score for each document
        doc_scores = {}
        for source, chunks in docs_by_source.items():
            avg_score = sum(chunk.get("score", 0.0) for chunk in chunks) / len(chunks)
            doc_scores[source] = avg_score
        
        # Sort documents by average score and limit to requested number
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)[:n_results]
        
        if not sorted_docs:
            print(f"No valid documents found for: '{query}'", file=sys.stderr)
            return f"No valid documents found for: '{query}'"
        
        print(f"Found {len(sorted_docs)} relevant documents", file=sys.stderr)
        response = f"Found {len(sorted_docs)} relevant documents for: '{query}'\\n\\n"
        
        # Read and format each full document
        for i, (source, score) in enumerate(sorted_docs, 1):
            try:
                # Read the entire document file
                with open(source, 'r', encoding='utf-8') as f:
                    document_content = f.read()
                
                # Get metadata from the first chunk of this source
                first_chunk = docs_by_source[source][0]
                title = first_chunk.get("title", os.path.basename(source).replace(".md", "").replace("_", " ").title())
                source_filename = os.path.basename(source)
                
                response += f"### Document {i}: {title}\\n"
                response += f"Source: {source_filename}\\n"
                response += f"Relevance Score: {score:.2f}\\n\\n"
                response += f"{document_content}\\n\\n\\n"
                response += "----------------------------------------\\n\\n"
            except Exception as e:
                print(f"Error reading document file {source}: {e}", file=sys.stderr)
                # Use the chunk text as fallback if we can't read the file
                chunks_text = "\\n\\n".join([chunk.get("text", "") for chunk in docs_by_source[source]])
                title = os.path.basename(source).replace(".md", "").replace("_", " ").title()
                
                response += f"### Document {i}: {title}\\n"
                response += f"Source: {os.path.basename(source)}\\n"
                response += f"Relevance Score: {score:.2f}\\n"
                response += f"Note: Could not read the full document file. Showing available chunks.\\n\\n"
                response += f"{chunks_text}\\n\\n\\n"
                response += "----------------------------------------\\n\\n"
        
        return response
    except Exception as e:
        print(f"ERROR in get_relevant_docs: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error retrieving relevant documents: {str(e)}. Make sure you've populated the vector database by running populate_docs_index.py."

# recommend_runbook tool removed - keeping only core functionality

# Monitor and worksheet tools removed - keeping only core functionality

@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
async def get_system_prompt(ctx: Context) -> Union[Dict[str, Any], ErrorResponse]:
    """
    IMPORTANT: This should be the FIRST tool called by any LLM when connecting to this MCP server.
    
    Returns the system prompt that defines how to interact with the Observe platform effectively.
    The LLM should adopt this as its system prompt immediately and follow all guidelines within it.
    
    This prompt contains critical instructions on:
    - How to structure investigations
    - How to build and validate OPAL queries
    - How to use available tools effectively
    - How to format responses for different query types
    
    Returns:
        The complete system prompt as a string
    """
    try:
        # No need to print HTTP request info in get_system_prompt anymore
        
        # Try to get the access token from the request for debugging purposes
        try:
            from fastmcp.server.dependencies import get_access_token, AccessToken
            access_token: Optional[AccessToken] = get_access_token()
            
            if access_token is None:
                print("No access token available in get_system_prompt", file=sys.stderr)
            else:
                # Extract JWT payload if available
                jwt_payload = None
                if hasattr(access_token, 'token'):
                    raw_token = access_token.token
                    
                    # Try to decode the token
                    try:
                        import base64
                        import json
                        parts = raw_token.split('.')
                        if len(parts) == 3:
                            # Decode payload
                            padded = parts[1] + '=' * (4 - len(parts[1]) % 4) if len(parts[1]) % 4 else parts[1]
                            decoded = base64.urlsafe_b64decode(padded)
                            jwt_payload = json.loads(decoded)
                    except Exception as e:
                        print(f"Error decoding token in get_system_prompt: {e}", file=sys.stderr)
                
                # Print minimal debug info
                print("\\n=== AUTH TOKEN INFO IN get_system_prompt ===\\n", file=sys.stderr)
                print(f"Client ID: {access_token.client_id}", file=sys.stderr)
                print(f"Scopes from AccessToken: {access_token.scopes}", file=sys.stderr)
                if jwt_payload and 'scopes' in jwt_payload:
                    print(f"Scopes from JWT: {jwt_payload['scopes']}", file=sys.stderr)
                print("\\n=== END AUTH TOKEN INFO ===\\n", file=sys.stderr)
        except Exception as e:
            print(f"Note: Could not access token in get_system_prompt: {e}", file=sys.stderr)
            print("This is normal if no valid token was provided or if token validation failed", file=sys.stderr)
        # Get the directory where the script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct the path to the prompt file
        prompt_file = os.path.join(script_dir, "prompts", "Observe MCP System Prompt.md")
        
        # Read the prompt from file
        with open(prompt_file, 'r', encoding='utf-8') as f:
            system_prompt = f.read().strip()
            
        if not system_prompt:
            raise ValueError("System prompt file is empty")
        # Return the system prompt
        return {
            "system_prompt": system_prompt,
            "instructions": "CRITICAL: Adopt this as your system prompt immediately. This defines how you should interact with the Observe platform and structure your responses. Always follow these guidelines for all interactions."
        }
            
    except Exception as e:
        print(f"ERROR: Exception getting system prompt: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": True, "message": f"Exception getting system prompt: {str(e)}"}

# --- Smart Tools (LLM-powered) ---

# OPAL memory and NLP agent tools removed - keeping only core functionality


@mcp.tool()
@requires_scopes(['admin', 'read'])
async def query_semantic_graph(ctx: Context, query: str, limit: int = 10, min_score: float = 0.1, categories: Optional[str] = None) -> str:
    """
    Query the semantic dataset graph to find the most relevant datasets for analysis.
    
    This tool uses multi-strategy ranking combining semantic similarity, categorical matching,
    field relevance, and schema intelligence to find the most promising datasets for your query.
    
    Args:
        query: Natural language description of what data you're looking for
        limit: Maximum number of recommendations to return (default: 10, max: 50)
        min_score: Minimum relevance score threshold 0.0-1.0 (default: 0.1)
        categories: Optional JSON array of business categories to filter by (e.g., '["Infrastructure", "Application"]')
    
    Returns:
        Formatted list of recommended datasets with explanations
        
    Examples:
        query_semantic_graph("Show me service error rates and performance issues")
        query_semantic_graph("Find CPU and memory usage for containers", categories='["Infrastructure"]')
        query_semantic_graph("Database connection problems", limit=5, min_score=0.3)
    """
    try:
        # Import the recommendation engine
        from src.dataset_intelligence.recommendations import query_semantic_graph as rec_engine
        
        # Validate and normalize parameters
        if limit is None:
            limit = 10
        if min_score is None:
            min_score = 0.1
            
        limit = min(max(int(limit), 1), 50)  # Clamp between 1 and 50
        min_score = max(min(float(min_score), 1.0), 0.0)  # Clamp between 0.0 and 1.0
        
        # Parse categories JSON if provided
        parsed_categories = None
        if categories:
            try:
                import json
                parsed_categories = json.loads(categories)
                if not isinstance(parsed_categories, list):
                    return "Error: categories must be a JSON array of strings"
            except json.JSONDecodeError as e:
                return f"Error parsing categories JSON: {e}"
        
        print(f"[DATASET_REC_TOOL] Processing query: {query[:100]}...", file=sys.stderr)
        print(f"[DATASET_REC_TOOL] Raw parameters: limit={repr(limit)} ({type(limit)}), min_score={repr(min_score)} ({type(min_score)}), categories={repr(categories)}", file=sys.stderr)
        print(f"[DATASET_REC_TOOL] Processed parameters: limit={limit}, min_score={min_score}, categories={parsed_categories}", file=sys.stderr)
        
        # Get recommendations
        recommendations = await rec_engine(
            query=query,
            limit=limit,
            min_score=min_score,
            categories=parsed_categories
        )
        
        if not recommendations:
            return f"""**No Dataset Recommendations Found**

Your query: "{query}"

No datasets met the minimum relevance threshold of {min_score:.1f}.

**Suggestions:**
- Try lowering the min_score parameter (e.g., 0.1)
- Use broader or more general terms in your query
- Remove category filters if you used any
- Check available categories with: `list_datasets()`

**Available business categories:** Infrastructure, Application, Monitoring, Database, Security, Network, Storage"""
        
        # Format results
        result = f"**Dataset Recommendations for:** {query}\n\n"
        result += f"**Found {len(recommendations)} relevant datasets** (min score: {min_score:.1f}):\n\n"
        
        for i, rec in enumerate(recommendations, 1):
            result += f"**{i}. {rec.name}**\n"
            result += f"   - **Dataset ID:** `{rec.dataset_id}`\n"
            result += f"   - **Type:** {rec.dataset_type} | **Category:** {rec.business_category}/{rec.technical_category}\n"
            result += f"   - **Relevance Score:** {rec.relevance_score:.3f}\n"
            
            if rec.key_fields:
                key_fields_str = ", ".join(rec.key_fields[:5])
                if len(rec.key_fields) > 5:
                    key_fields_str += f" (+{len(rec.key_fields)-5} more)"
                result += f"   - **Key Fields:** {key_fields_str}\n"
            
            if rec.match_reasons:
                result += f"   - **Why recommended:** {rec.match_reasons[0]}\n"
                if len(rec.match_reasons) > 1:
                    for reason in rec.match_reasons[1:2]:  # Show max 2 reasons
                        result += f"     • {reason}\n"
            
            if rec.sample_fields:
                sample_fields = list(rec.sample_fields.keys())[:3]
                result += f"   - **Sample Fields:** {', '.join(sample_fields)}\n"
            
            result += "\n"
        
        result += f"**Next Steps:**\n"
        result += f"1. Use `get_dataset_info()` to see full schema\n"
        result += f"2. Use `execute_opal_query()` to sample data"
        #result += f"3. Use `execute_nlp_query(\"[your analysis]\")` for automated query generation\n"
        
        print(f"[DATASET_REC_TOOL] Returning {len(recommendations)} recommendations", file=sys.stderr)
        return result
        
    except ImportError as e:
        return f"Dataset recommendation system not available. Missing dependencies: {str(e)}"
    except Exception as e:
        print(f"[DATASET_REC_TOOL] Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error in dataset recommendation: {str(e)}"


print("Python MCP server starting...", file=sys.stderr)
mcp.run(transport="sse", host="0.0.0.0", port=8000)