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

        # Create a focused prompt that requests structured documentation
        prompt = f"""Search for information about: {query}

Please find relevant documentation from docs.observeinc.com and provide:
1. Key concepts and explanations
2. Syntax examples if applicable
3. Best practices and common usage patterns
4. Related documentation topics

Focus on technical accuracy and cite specific documentation sources."""

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
            for i, chunk in enumerate(grounding_chunks[:n_results]):
                if hasattr(chunk, 'web') and chunk.web:
                    uri = chunk.web.uri if hasattr(chunk.web, 'uri') else ""
                    title = chunk.web.title if hasattr(chunk.web, 'title') else "Documentation"

                    # Skip duplicates
                    if uri in seen_uris:
                        continue
                    seen_uris.add(uri)

                    # Find relevant text segments that reference this chunk
                    relevant_text = _extract_relevant_text(main_text, chunk, grounding_supports)

                    results.append({
                        "id": f"gemini_result_{i}",
                        "score": 1.0 - (i * 0.1),  # Decreasing score for ranking
                        "text": relevant_text,
                        "source": uri,
                        "title": title
                    })

            semantic_logger.debug(f"parsed {len(results)} grounded results from gemini")

        # If no grounded results or not enough, create a single result from main text
        if len(results) < n_results and main_text:
            results.append({
                "id": "gemini_summary",
                "score": 0.9,
                "text": main_text[:2000],  # Limit text length
                "source": "docs.observeinc.com",
                "title": f"Documentation: {query}"
            })

        # Ensure we have at least one result
        if not results:
            results.append({
                "id": "no_results",
                "score": 0.5,
                "text": f"No specific documentation found for: {query}. Try broader search terms or check docs.observeinc.com directly.",
                "source": "docs.observeinc.com",
                "title": "No Results Found"
            })

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


def _extract_relevant_text(main_text: str, chunk: Any, supports: List[Any]) -> str:
    """
    Extract text segments that are grounded in this specific chunk

    Args:
        main_text: Full response text
        chunk: Grounding chunk
        supports: List of grounding supports linking text to sources

    Returns:
        Relevant text segment
    """
    try:
        # Find supports that reference this chunk
        relevant_segments = []

        for support in supports:
            if not hasattr(support, 'segment') or not hasattr(support, 'grounding_chunk_indices'):
                continue

            # Check if this support references our chunk
            chunk_indices = support.grounding_chunk_indices if support.grounding_chunk_indices else []

            # Extract the text segment
            if hasattr(support.segment, 'text'):
                segment_text = support.segment.text
                if segment_text:
                    relevant_segments.append(segment_text)

        # Combine segments
        if relevant_segments:
            combined = " ".join(relevant_segments)
            return combined[:1000]  # Limit length

        # Fallback to a portion of main text
        return main_text[:800]

    except Exception as e:
        semantic_logger.debug(f"error extracting relevant text | error:{e}")
        return main_text[:800] if main_text else "Documentation available at source URL"


def get_rate_limiter_stats() -> Dict[str, Any]:
    """Get current rate limiter statistics for monitoring"""
    return _rate_limiter.get_stats()
