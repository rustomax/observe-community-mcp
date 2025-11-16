#!/usr/bin/env python3
"""
Test script to inspect raw Gemini grounding chunks without truncation
"""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from google import genai
from google.genai import types

# Get API key
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    print("Error: GEMINI_API_KEY not set")
    sys.exit(1)

# Initialize client
client = genai.Client(api_key=api_key)

# Test query
query = "OPAL make_col type casting"
domain_scope = "site:docs.observeinc.com"
scoped_query = f"{domain_scope} {query}"

# Configure search
grounding_tool = types.Tool(google_search=types.GoogleSearch())
config = types.GenerateContentConfig(
    tools=[grounding_tool],
    temperature=0.1,
)

# Create prompt
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

# Make API call
print(f"Query: {scoped_query}\n")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=scoped_query,
    config=config,
)

# Inspect response structure
print("=" * 80)
print("RESPONSE STRUCTURE INSPECTION")
print("=" * 80)

if hasattr(response, 'candidates') and response.candidates:
    candidate = response.candidates[0]

    if hasattr(candidate, 'grounding_metadata'):
        grounding_metadata = candidate.grounding_metadata

        # Check for grounding chunks
        if hasattr(grounding_metadata, 'grounding_chunks'):
            chunks = grounding_metadata.grounding_chunks
            print(f"\nFound {len(chunks)} grounding chunks\n")

            for i, chunk in enumerate(chunks[:3]):  # Only inspect first 3
                print(f"\n{'=' * 80}")
                print(f"CHUNK {i}")
                print(f"{'=' * 80}")

                if hasattr(chunk, 'web') and chunk.web:
                    web = chunk.web

                    # URI
                    if hasattr(web, 'uri'):
                        print(f"\nURI: {web.uri}")

                    # Title
                    if hasattr(web, 'title'):
                        print(f"Title: {web.title}")

                    # Snippet
                    if hasattr(web, 'snippet'):
                        snippet = web.snippet
                        print(f"\nSnippet length: {len(snippet)} characters")
                        print(f"Snippet preview (first 200 chars):\n{snippet[:200]}...")
                        print(f"\nFull snippet:\n{snippet}")

                    # Text
                    if hasattr(web, 'text'):
                        text = web.text
                        print(f"\nText length: {len(text)} characters")
                        print(f"Text preview (first 200 chars):\n{text[:200]}...")
                        print(f"\nFull text:\n{text}")

                    # Check all attributes
                    print(f"\nAll web attributes: {dir(web)}")

        # Check for grounding supports
        if hasattr(grounding_metadata, 'grounding_supports'):
            supports = grounding_metadata.grounding_supports
            print(f"\n\nFound {len(supports)} grounding supports")

            for i, support in enumerate(supports[:2]):  # Only inspect first 2
                print(f"\n--- Support {i} ---")
                if hasattr(support, 'segment') and hasattr(support.segment, 'text'):
                    segment_text = support.segment.text
                    print(f"Segment text length: {len(segment_text)} characters")
                    print(f"Segment text: {segment_text}")

                if hasattr(support, 'grounding_chunk_indices'):
                    print(f"References chunks: {support.grounding_chunk_indices}")

print("\n" + "=" * 80)
print("MAIN RESPONSE TEXT")
print("=" * 80)
if hasattr(response, 'text'):
    main_text = response.text
    print(f"\nMain text length: {len(main_text)} characters")
    print(f"\nFull main text:\n{main_text}")
