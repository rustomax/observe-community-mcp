#!/usr/bin/env python3
"""
Observe MCP Server
A Model Context Protocol server that provides access to Observe API functionality
using organized modules for better maintainability and reusability.
"""

import os
import sys
import json
import base64
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Optional, List, Union, TypedDict

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
    print(f"Pinecone import successful. Version: {pinecone.__version__}", file=sys.stderr)
    
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
    execute_opal_query as observe_execute_opal_query,
    create_monitor as observe_create_monitor,
    list_monitors as observe_list_monitors,
    get_monitor as observe_get_monitor,
    export_worksheet as observe_export_worksheet
)

from fastmcp import FastMCP, Context
from fastmcp.server.auth import BearerAuthProvider
from fastmcp.server.dependencies import get_access_token, AccessToken

# Get public key from environment variable, or use a default if not set
public_key_pem = os.getenv("PUBLIC_KEY_PEM", "")

# If public key is not set in environment, log a warning
if not public_key_pem:
    print("WARNING: PUBLIC_KEY_PEM not found in environment variables. Authentication may fail.", file=sys.stderr)
    print("Please set PUBLIC_KEY_PEM in your .env file with the correct public key.", file=sys.stderr)

# Configure BearerAuthProvider with the public key
auth = BearerAuthProvider(public_key=public_key_pem)

mcp = FastMCP(name="observe-epic", auth=auth)

# --- Scope-based Protection Middleware ---

def requires_scopes(required_scopes: List[str]):
    """
    Middleware decorator that protects tools based on JWT token scopes.
    
    Args:
        required_scopes: List of scopes required to access the tool.
        
    Returns:
        Decorator function that wraps the tool function.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx: Context, *args, **kwargs):
            # Get JWT token scopes
            jwt_scopes = []
            try:
                # Get the access token
                access_token = get_access_token()
                
                # Try to get scopes from AccessToken object first
                if access_token.scopes:
                    jwt_scopes = access_token.scopes
                # If not available, try to extract from raw token
                elif hasattr(access_token, 'token'):
                    try:
                        # Decode JWT payload
                        parts = access_token.token.split('.')
                        if len(parts) == 3:
                            padded = parts[1] + '=' * (4 - len(parts[1]) % 4) if len(parts[1]) % 4 else parts[1]
                            decoded = base64.urlsafe_b64decode(padded)
                            payload = json.loads(decoded)
                            if 'scopes' in payload:
                                jwt_scopes = payload['scopes']
                    except Exception as e:
                        print(f"Error extracting scopes from JWT: {e}", file=sys.stderr)
                        
                # Check if user has required scopes
                has_required_scopes = any(scope in jwt_scopes for scope in required_scopes)
                if not has_required_scopes:
                    print(f"Access denied: Required scopes {required_scopes}, but user has {jwt_scopes}", file=sys.stderr)
                    return {
                        "error": True,
                        "message": f"Access denied: You don't have the required permissions. Required: {required_scopes}"
                    }
                    
                # User has required scopes, proceed with the function
                return await func(ctx, *args, **kwargs)
            except Exception as e:
                print(f"Error in requires_scopes middleware: {e}", file=sys.stderr)
                return {
                    "error": True,
                    "message": f"Authentication error: {str(e)}"
                }
        return wrapper
    return decorator

# --- MCP Tools (Refactored to use organized modules) ---

@mcp.tool()
async def decode_jwt_token(token: str) -> Dict[str, Any]:
    """
    Decode a JWT token and return its contents.
    This is useful for debugging JWT tokens.
    """
    try:
        # Split the token into header, payload, and signature
        parts = token.split('.')
        if len(parts) != 3:
            return {"error": "Invalid JWT token format"}
        
        # Decode header
        header_padded = parts[0] + '=' * (4 - len(parts[0]) % 4) if len(parts[0]) % 4 else parts[0]
        header_decoded = base64.urlsafe_b64decode(header_padded)
        header = json.loads(header_decoded)
        
        # Decode payload
        payload_padded = parts[1] + '=' * (4 - len(parts[1]) % 4) if len(parts[1]) % 4 else parts[1]
        payload_decoded = base64.urlsafe_b64decode(payload_padded)
        payload = json.loads(payload_decoded)
        print(f"Header: {json.dumps(header, indent=2)}", file=sys.stderr)
        print(f"Payload: {json.dumps(payload, indent=2)}", file=sys.stderr)
        print("\\n=== END JWT TOKEN DEBUG INFO ===\\n", file=sys.stderr)
        
        return {
            "header": header,
            "payload": payload,
            "signature_present": len(parts[2]) > 0
        }
    except Exception as e:
        print(f"Error decoding JWT token: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        
        return {"error": f"Exception decoding JWT token: {str(e)}"}

@mcp.tool()
@requires_scopes(['admin'])
async def admin_system_info(ctx: Context) -> Dict[str, Any]:
    """
    Get system information that is only available to users with admin scope.
    This is a protected endpoint that requires the 'admin' scope in the JWT token.
    """
    try:
        # Define sensitive environment variable patterns to filter out
        sensitive_patterns = [
            'key', 'secret', 'password', 'token', 'credential', 'auth', 
            'api_', 'cert', 'private', 'salt', 'hash'
        ]
        
        # Filter environment variables to exclude sensitive information
        filtered_env = {}
        for key, value in os.environ.items():
            # Skip any env var with sensitive patterns in key
            if any(pattern in key.lower() for pattern in sensitive_patterns):
                filtered_env[key] = "[REDACTED]"
            else:
                filtered_env[key] = value
                
        system_info = {
            "python_version": sys.version,
            "python_path": sys.path,
            "environment": filtered_env,
            "server_time": datetime.now().isoformat(),
            "server_pid": os.getpid(),
        }
        
        return {
            "success": True,
            "message": "Admin access granted",
            "system_info": system_info
        }
    except Exception as e:
        return {
            "error": True,
            "message": f"Error getting system info: {str(e)}"
        }

@mcp.tool()
async def public_server_info(ctx: Context) -> Dict[str, Any]:
    """
    Get basic public server information that is available to all users.
    This endpoint does not require any specific scope.
    """
    try:
        server_info = {
            "server_name": "observe-epic",
            "server_version": "1.0.0",
            "server_time": datetime.now().isoformat(),
            "python_version": sys.version.split()[0]  # Just the version number, not the full string
        }
        
        return {
            "success": True,
            "server_info": server_info
        }
    except Exception as e:
        return {
            "error": True,
            "message": f"Error getting public server info: {str(e)}"
        }

@mcp.tool()
async def get_auth_token_info(ctx: Context) -> Dict[str, Any]:
    """
    Get information about the current authentication status.
    """
    try:
        # Get the access token from the request
        access_token: AccessToken = get_access_token()
        
        # Initialize the result dictionary with basic info
        result = {
            "authenticated": True,
            "client_id": access_token.client_id,
            "token_type": "Bearer"
        }
        
        # Add expiration if available
        if hasattr(access_token, 'expires_at'):
            result["expires_at"] = access_token.expires_at
        
        # Get scopes - first try AccessToken.scopes
        scopes = []
        if access_token.scopes:
            scopes = access_token.scopes
            result["scopes"] = scopes
        
        # If no scopes found, try to extract from JWT payload
        if not scopes and hasattr(access_token, 'token'):
            try:
                # Decode JWT payload to get scopes
                parts = access_token.token.split('.')
                if len(parts) == 3:
                    padded = parts[1] + '=' * (4 - len(parts[1]) % 4) if len(parts[1]) % 4 else parts[1]
                    decoded = base64.urlsafe_b64decode(padded)
                    payload = json.loads(decoded)
                    
                    # Extract useful claims for the client
                    if 'scopes' in payload:
                        scopes = payload['scopes']
                        result["scopes"] = scopes
                    
                    # Add other useful claims
                    for claim in ['iss', 'aud', 'exp', 'iat', 'sub']:
                        if claim in payload:
                            result[claim] = payload[claim]
            except Exception as e:
                # Don't expose error details to client
                pass
        
        # Add permissions information based on scopes
        result["permissions"] = {
            "admin_access": "admin" in scopes,
            "read_access": any(s in scopes for s in ["read", "admin"]),
            "write_access": any(s in scopes for s in ["write", "admin"])
        }
        
        # Minimal logging for server-side debugging
        print(f"Auth info requested by {access_token.client_id}, scopes: {scopes}", file=sys.stderr)
        
        return result
    except Exception as e:
        print(f"Error getting auth token info: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        
        # Return error information
        return {
            "error": f"Exception getting auth token info: {str(e)}",
            "is_authenticated": False,
            "note": "This may indicate that no valid token was provided or that token validation failed"
        }

# --- Observe API Tools (using refactored modules) ---

@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
async def execute_opal_query(ctx: Context, query: str, dataset_id: str, time_range: Optional[str] = "1h", start_time: Optional[str] = None, end_time: Optional[str] = None, row_count: Optional[int] = 1000, format: Optional[str] = "csv") -> str:
    """
    Execute an OPAL query on a dataset.
    
    Args:
        query: The OPAL query to execute
        dataset_id: The ID of the dataset to query
        time_range: Time range for the query (e.g., "1h", "1d", "7d"). Used if start_time and end_time are not provided.
        start_time: Optional start time in ISO format (e.g., "2023-04-20T16:20:00Z")
        end_time: Optional end time in ISO format (e.g., "2023-04-20T16:30:00Z")
        row_count: Maximum number of rows to return (default: 1000, max: 100000)
        format: Output format, either "csv" or "ndjson" (default: "csv")
    """
    return await observe_execute_opal_query(
        query=query,
        dataset_id=dataset_id,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time,
        row_count=row_count,
        format=format
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

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def recommend_runbook(ctx: Context, query: str) -> str:
    """
    Analyze a user query and recommend a runbook for Observe data.
    
    This function suggests a sequence of steps to fulfill the request using existing Observe tools.
    It identifies relevant datasets, metrics, and visualization approaches based on the query.
    
    Args:
        query: The user's query about Observe data or troubleshooting needs
        
    Returns:
        A recommended runbook with step-by-step instructions
    """
    try:
        # Import required modules
        import os
        from collections import defaultdict
        
        print(f"Searching for runbooks related to: '{query}'", file=sys.stderr)
        
        # Use the new search module to get runbook results
        chunk_results = search_runbooks(query, n_results=10)  # Get more results to ensure we have enough chunks from relevant runbooks
        
        if not chunk_results:
            return "No relevant runbooks found for your query. Please try a different search term."
        
        # Group results by source file and calculate average score
        runbooks_by_source = defaultdict(list)
        for result in chunk_results:
            source = result.get("source", "")
            if source and source != "error":
                runbooks_by_source[source].append(result)
        
        if not runbooks_by_source:
            return "No relevant runbooks found for your query. Please try a different search term."
        
        # Calculate average score for each runbook
        runbook_scores = {}
        for source, matches in runbooks_by_source.items():
            avg_score = sum(match.get("score", 0.0) for match in matches) / len(matches)
            runbook_scores[source] = avg_score
        
        # Sort runbooks by average score and get only the top one
        sorted_runbooks = sorted(runbook_scores.items(), key=lambda x: x[1], reverse=True)[:1]  # Get only top 1 runbook
        
        if not sorted_runbooks:
            return "No relevant runbooks found for your query. Please try a different search term."
            
        # Get the top runbook
        source, score = sorted_runbooks[0]
        
        # Format result
        try:
            # Read the entire runbook file
            with open(source, 'r', encoding='utf-8') as f:
                runbook_content = f.read()
            
            # Get metadata from the first chunk of this source
            first_match = runbooks_by_source[source][0]
            title = first_match.get("title", os.path.basename(source).replace('.md', '').replace('_', ' ').title())
            source_filename = os.path.basename(source)
            
            response = f"# {title}\\n\\n"
            response += f"**Source:** {source_filename} (Relevance: {score:.2f})\\n\\n"
            response += f"**Content:**\\n\\n{runbook_content}"
            
            return response
            
        except Exception as e:
            print(f"Error reading runbook file {source}: {e}", file=sys.stderr)
            return f"Error: Could not read the runbook file {os.path.basename(source)}: {str(e)}"
                
    except Exception as e:
        print(f"Error in recommend_runbook: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error recommending runbook: {str(e)}. Make sure you've populated the runbooks vector database by running populate_runbooks_index.py."

# --- MonitorV2 Endpoints ---

@mcp.tool()
@requires_scopes(['admin', 'write'])
async def create_monitor(ctx: Context, name: str, description: str, query: str, dataset_id: str, 
                      threshold: float, window: str, frequency: str = "5m", 
                      actions: Optional[List[str]] = None) -> Union[Dict[str, Any], ErrorResponse]:
    """
    Create a new MonitorV2 and bind to actions.
    
    IMPORTANT: The OPAL query must output a numeric value that can be compared against the threshold.
    
    Examples:
    
    1. Error rate monitor (alerts when error count > 3 in 5 minutes):
       create_monitor(
           name="Cart Errors Monitor", 
           description="Shopping cart errors are high", 
           query="filter container = \\"cartservice\\" | filter body ~ \\"error\\" | timechart 5m, count()", 
           dataset_id="42428942", 
           threshold=3.0, 
           window="5m"
       )
       
    2. Latency monitor (alerts when p95 latency > 500ms):
       create_monitor(
           name="Cart Latency Monitor", 
           description="Shopping cart latency is high", 
           query="filter service_name = \\"cartservice\\" | align 1m, frame(back: 5m), latency:tdigest_quantile(tdigest_combine(m_tdigest(\\"span_duration_5m\\")), 0.95) | timechart 5m, latency", 
           dataset_id="42160988", 
           threshold=500000000, 
           window="5m"
       )
       
    3. Metric-based error count monitor (alerts when error count > 5 in 10 minutes):
       create_monitor(
           name="CartService Error Rate Alert", 
           description="Alert when CartService error rate exceeds threshold by monitoring error counts", 
           query="filter service_name = \\"cartservice\\" and metric = \\"span_error_count_5m\\" and value > 0 | timechart 5m, count()", 
           dataset_id="42160988", 
           threshold=5.0, 
           window="10m",
           frequency="5m"
       )
    
    Args:
        name: Name of the monitor
        description: Description of the monitor
        query: OPAL query to execute (must output a numeric value to compare against threshold)
        dataset_id: Dataset ID to query
        threshold: Threshold value for alerting
        window: Time window for evaluation (e.g., "5m", "1h")
        frequency: How often to run the monitor (e.g., "5m", "1h")
        actions: List of action IDs to trigger when monitor fires
        
    Returns:
        The created MonitorV2 object
    """
    return await observe_create_monitor(
        name=name,
        description=description,
        query=query,
        dataset_id=dataset_id,
        threshold=threshold,
        window=window,
        frequency=frequency,
        actions=actions
    )

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def list_monitors(ctx: Context, name_exact: Optional[str] = None, name_substring: Optional[str] = None) -> Union[List[Dict[str, Any]], ErrorResponse]:
    """
    List MonitorV2 instances with optional filters.
    
    Args:
        name_exact: Limit to an exact string match
        name_substring: Limit to a substring match
        
    Returns:
        An array of monitor objects
    """
    return await observe_list_monitors(
        name_exact=name_exact,
        name_substring=name_substring
    )

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def get_monitor(ctx: Context, monitor_id: str) -> Union[Dict[str, Any], ErrorResponse]:
    """
    Get a specific MonitorV2 by ID.
    
    Args:
        monitor_id: The ID of the monitor to retrieve
        
    Returns:
        The monitor object with its complete structure
    """
    return await observe_get_monitor(monitor_id=monitor_id)

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def export_worksheet(ctx: Context, worksheet_id: str, time_range: Optional[str] = "15m", start_time: Optional[str] = None, end_time: Optional[str] = None) -> str:
    """
    Export data from an Observe worksheet.
    
    Args:
        worksheet_id: The ID of the worksheet to export
        time_range: Time range for the export (e.g., "15m", "1h", "24h"). Used if start_time and end_time are not provided. Defaults to "15m".
        start_time: Optional start time in ISO format (e.g., "2025-07-21T00:00:00Z")
        end_time: Optional end time in ISO format (e.g., "2025-07-22T00:00:00Z")
        
    Returns:
        The exported worksheet data as a string
    """
    return await observe_export_worksheet(
        worksheet_id=worksheet_id,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time
    )

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
            access_token: AccessToken = get_access_token()
            
            # Extract JWT payload if available
            jwt_payload = None
            if hasattr(access_token, 'token'):
                raw_token = access_token.token
                
                # Try to decode the token
                try:
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

print("Python MCP server starting...", file=sys.stderr)
mcp.run(transport="sse", host="0.0.0.0", port=8000)