"""
Gemini-powered documentation search using Google Search grounding

Replaces local BM25 index with real-time web search against docs.observeinc.com,
eliminating need for documentation archives and providing always-current results.
"""

import os
import time
from typing import List, Dict, Any
from datetime import datetime, timedelta
from collections import deque
from src.logging import semantic_logger

# Import telemetry decorators
try:
    from src.telemetry.decorators import trace_mcp_tool
    from src.telemetry.utils import add_mcp_context
except ImportError:
    def trace_mcp_tool(tool_name=None, record_args=False, record_result=False):
        def decorator(func):
            return func
        return decorator
    def add_mcp_context(span, **kwargs):
        pass


class RateLimiter:
    """
    Rate limiter for Gemini API calls

    Tier 1 limits: 500 requests per day for Google Search grounding
    We'll be conservative and limit to 400 RPD to leave buffer.
    """

    def __init__(self, max_requests_per_day: int = 400):
        self.max_requests = max_requests_per_day
        self.requests = deque()
        self.window = timedelta(days=1)

    def _clean_old_requests(self):
        """Remove requests older than the time window"""
        cutoff = datetime.now() - self.window
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()

    def can_make_request(self) -> bool:
        """Check if we can make a request without exceeding limits"""
        self._clean_old_requests()
        return len(self.requests) < self.max_requests

    def record_request(self):
        """Record that a request was made"""
        self.requests.append(datetime.now())

    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limiter statistics"""
        self._clean_old_requests()
        return {
            "requests_in_window": len(self.requests),
            "max_requests": self.max_requests,
            "remaining": self.max_requests - len(self.requests),
            "window_hours": 24
        }


# Global rate limiter instance
_rate_limiter = RateLimiter()


async def search_docs_gemini(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search Observe documentation using Gemini Search grounding

    Args:
        query: Search query text
        n_results: Number of results to return (default: 5)

    Returns:
        List of search results with metadata, compatible with previous search format
    """
    try:
        # Check rate limits
        if not _rate_limiter.can_make_request():
            stats = _rate_limiter.get_stats()
            error_msg = f"Rate limit reached: {stats['requests_in_window']}/{stats['max_requests']} requests used in last 24h. Please try again later."
            semantic_logger.warning(f"gemini rate limit exceeded | {error_msg}")
            return [{
                "id": "rate_limit",
                "score": 1.0,
                "text": error_msg,
                "source": "rate_limiter",
                "title": "Rate Limit Exceeded"
            }]

        semantic_logger.info(f"gemini docs search | query:'{query[:100]}' | n_results:{n_results}")

        # Import Gemini client
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            error_msg = "Gemini API client not installed. Install with: pip install google-genai"
            semantic_logger.error(f"gemini import failed | {error_msg}")
            return [{
                "id": "import_error",
                "score": 1.0,
                "text": error_msg,
                "source": "error",
                "title": "Gemini API Not Available"
            }]

        # Get API key from environment
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            error_msg = "GEMINI_API_KEY environment variable not set"
            semantic_logger.error(f"gemini config error | {error_msg}")
            return [{
                "id": "config_error",
                "score": 1.0,
                "text": error_msg,
                "source": "error",
                "title": "Gemini API Key Missing"
            }]

        # Initialize Gemini client
        client = genai.Client(api_key=api_key)

        # Construct domain-scoped search query
        # Restrict to docs.observeinc.com for official Observe documentation
        domain_scope = "site:docs.observeinc.com"
        scoped_query = f"{domain_scope} {query}"

        # Configure with Google Search grounding tool
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(
            tools=[grounding_tool],
            temperature=0.1,  # Low temperature for factual documentation retrieval
        )

        # Create a focused prompt that requests ONLY grounded documentation
        prompt = f"""Search docs.observeinc.com for: {query}

CRITICAL INSTRUCTIONS:
1. ONLY return information directly from the actual documentation pages you find via search
2. Quote OPAL code examples EXACTLY as written in the documentation - do not modify syntax
3. DO NOT add examples, explanations, or syntax from your general knowledge
4. DO NOT generate code examples if they are not present in the actual documentation
5. If documentation is found but doesn't contain what was asked for, say so explicitly

For each documentation page found, provide:
- Direct quotes or very close paraphrases from the actual page content
- OPAL code examples exactly as they appear (preserve all syntax)
- The specific page where this information was found"""

        # Record request before making it
        _rate_limiter.record_request()

        # Make the API call
        start_time = time.time()
        response = client.models.generate_content(
            model="gemini-2.5-flash",  # Fast and cost-effective
            contents=scoped_query,
            config=config,
        )
        elapsed = time.time() - start_time

        semantic_logger.info(f"gemini search complete | elapsed:{elapsed:.2f}s")

        # Parse the response
        results = _parse_gemini_response(response, query, n_results)

        # Log statistics
        stats = _rate_limiter.get_stats()
        semantic_logger.info(
            f"gemini stats | results:{len(results)} | "
            f"rate_limit:{stats['requests_in_window']}/{stats['max_requests']} | "
            f"remaining:{stats['remaining']}"
        )

        return results

    except Exception as e:
        semantic_logger.error(f"gemini search error | error:{e}")
        return [{
            "id": "error",
            "score": 1.0,
            "text": f"Error in Gemini search: {str(e)}. Your query was: {query}",
            "source": "error",
            "title": "Gemini Search Error"
        }]


def _parse_gemini_response(response: Any, query: str, n_results: int) -> List[Dict[str, Any]]:
    """
    Parse Gemini response and extract grounded sources

    Args:
        response: Gemini API response object
        query: Original search query (for logging)
        n_results: Maximum number of results to return

    Returns:
        Formatted search results
    """
    try:
        results = []

        # Extract the main text response
        if hasattr(response, 'text'):
            main_text = response.text
        else:
            main_text = str(response)

        # Extract grounding metadata if available
        grounding_metadata = None
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata'):
                grounding_metadata = candidate.grounding_metadata

        # If we have grounding metadata, use it to create structured results
        if grounding_metadata:
            # Extract search entry point and grounding chunks
            grounding_chunks = []
            if hasattr(grounding_metadata, 'grounding_chunks'):
                grounding_chunks = grounding_metadata.grounding_chunks

            # Extract grounding supports (links between text and sources)
            grounding_supports = []
            if hasattr(grounding_metadata, 'grounding_supports'):
                grounding_supports = grounding_metadata.grounding_supports

            # Create result entries from grounding chunks
            seen_uris = set()
            seen_text = set()  # Track unique text content
            for i, chunk in enumerate(grounding_chunks[:n_results]):
                if hasattr(chunk, 'web') and chunk.web:
                    uri = chunk.web.uri if hasattr(chunk.web, 'uri') else ""
                    title = chunk.web.title if hasattr(chunk.web, 'title') else "Documentation"

                    # CRITICAL: Only include results from docs.observeinc.com
                    # Check both URI and title since URI may be a redirect URL
                    is_observe_doc = (
                        ("docs.observeinc.com" in uri.lower() if uri else False) or
                        ("observeinc.com" in title.lower() if title else False)
                    )

                    if not is_observe_doc:
                        semantic_logger.debug(f"skipping non-observe result | title:{title} | uri:{uri}")
                        continue

                    # Find relevant text segments that reference this chunk
                    relevant_text = _extract_relevant_text(main_text, chunk, grounding_supports, i)

                    # Skip duplicates by URI or by text content
                    text_hash = relevant_text[:200]  # Use first 200 chars as hash
                    if uri in seen_uris or text_hash in seen_text:
                        continue
                    seen_uris.add(uri)
                    seen_text.add(text_hash)

                    results.append({
                        "id": f"gemini_result_{i}",
                        "score": 1.0 - (i * 0.1),  # Decreasing score for ranking
                        "text": relevant_text,
                        "source": uri,
                        "title": title
                    })

            semantic_logger.debug(f"parsed {len(results)} grounded results from gemini")

        # ONLY return grounded results - no AI-generated fallback content
        if not results:
            # No grounded results found - suggest query rewording
            suggestion = _generate_query_suggestions(query)
            results.append({
                "id": "no_grounded_results",
                "score": 0.0,
                "text": f"No documentation found for: '{query}'.\n\nSuggestions:\n{suggestion}\n\nTry:\n- Using different keywords (e.g., 'OPAL' instead of 'SQL')\n- Breaking complex queries into simpler parts\n- Searching for specific function names or verbs\n- Checking docs.observeinc.com directly",
                "source": "search_assistant",
                "title": "No Grounded Results - Try Rewording Query"
            })
            semantic_logger.info(f"no grounded results found for query: '{query}'")

        return results[:n_results]

    except Exception as e:
        semantic_logger.error(f"error parsing gemini response | error:{e}")
        return [{
            "id": "parse_error",
            "score": 1.0,
            "text": f"Error parsing search results: {str(e)}",
            "source": "error",
            "title": "Parse Error"
        }]


def _generate_query_suggestions(query: str) -> str:
    """
    Generate helpful suggestions for rewording failed queries

    Args:
        query: Original search query that returned no results

    Returns:
        Suggestion text
    """
    suggestions = []

    # Detect SQL-specific terms and suggest OPAL alternatives
    sql_terms = {
        'select': 'Use OPAL verbs like filter, make_col, aggregate',
        'from': 'OPAL queries start with dataset reference or align',
        'where': 'Use filter verb in OPAL',
        'group by': 'Use group_by() or statsby in OPAL',
        'order by': 'Use sort verb in OPAL',
        'join': 'Try searching for "lookup" or "join" in OPAL',
        'over': 'OPAL uses window() function, not OVER clause',
        'partition by': 'Use group_by() within window() in OPAL',
    }

    query_lower = query.lower()
    for sql_term, opal_alternative in sql_terms.items():
        if sql_term in query_lower:
            suggestions.append(f"- Instead of '{sql_term}': {opal_alternative}")

    # General suggestions if no SQL terms detected
    if not suggestions:
        suggestions.append("- Try searching for specific OPAL function names (filter, statsby, window)")
        suggestions.append("- Search for the verb/operation you want to perform")
        suggestions.append("- Use more general terms (e.g., 'aggregation' instead of specific syntax)")

    return "\n".join(suggestions)


def _extract_relevant_text(main_text: str, chunk: Any, supports: List[Any], chunk_index: int) -> str:
    """
    Extract text segments that are grounded in this specific chunk

    Args:
        main_text: Full response text
        chunk: Grounding chunk
        supports: List of grounding supports linking text to sources
        chunk_index: Index of this chunk in the grounding_chunks list

    Returns:
        Relevant text segment unique to this chunk
    """
    try:
        # First priority: Use the chunk's own content if available
        if hasattr(chunk, 'web') and chunk.web:
            # Try to get snippet or excerpt from the web chunk itself
            # DO NOT truncate - Gemini already provides appropriately-sized chunks
            if hasattr(chunk.web, 'snippet') and chunk.web.snippet:
                semantic_logger.debug(f"using chunk snippet | length:{len(chunk.web.snippet)}")
                return chunk.web.snippet
            if hasattr(chunk.web, 'text') and chunk.web.text:
                semantic_logger.debug(f"using chunk text | length:{len(chunk.web.text)}")
                return chunk.web.text

        # Second priority: Find supports that reference THIS specific chunk
        relevant_segments = []
        for support in supports:
            if not hasattr(support, 'segment') or not hasattr(support, 'grounding_chunk_indices'):
                continue

            # Check if this support references our specific chunk index
            chunk_indices = support.grounding_chunk_indices if support.grounding_chunk_indices else []
            if chunk_index in chunk_indices:
                # Extract the text segment for THIS chunk only
                if hasattr(support.segment, 'text'):
                    segment_text = support.segment.text
                    if segment_text and segment_text not in relevant_segments:
                        relevant_segments.append(segment_text)

        # Combine segments specific to this chunk - DO NOT truncate
        if relevant_segments:
            combined = " ".join(relevant_segments)
            semantic_logger.debug(f"using combined segments | count:{len(relevant_segments)} | length:{len(combined)}")
            return combined

        # Last resort: Use offset portion of main text to ensure uniqueness
        # Use chunk_index to get different portions for different chunks
        offset = chunk_index * 2000
        fallback = main_text[offset:offset+3000] if len(main_text) > offset else main_text[:3000]
        semantic_logger.debug(f"using fallback text | offset:{offset} | length:{len(fallback)}")
        return fallback

    except Exception as e:
        semantic_logger.debug(f"error extracting relevant text | error:{e}")
        return main_text[:3000] if main_text else "Documentation available at source URL"


def get_rate_limiter_stats() -> Dict[str, Any]:
    """Get current rate limiter statistics for monitoring"""
    return _rate_limiter.get_stats()
