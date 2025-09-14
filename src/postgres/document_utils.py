"""
Document processing utilities for PostgreSQL BM25

Provides utility functions for finding and chunking markdown files
for BM25 indexing, extracted from the original Pinecone implementation.
"""

import os
import glob
import re
from typing import List, Dict, Any


def find_markdown_files(directory: str) -> List[str]:
    """Find all markdown files in the given directory recursively"""
    if not os.path.exists(directory):
        print(f"Directory does not exist: {directory}")
        return []

    md_files = []
    for ext in ["md", "markdown"]:
        md_files.extend(glob.glob(f"{directory}/**/*.{ext}", recursive=True))

    return md_files


def chunk_markdown(file_path: str, chunk_size: int = 1000, chunk_type: str = "docs") -> List[Dict[str, Any]]:
    """
    Split markdown file into chunks of approximately chunk_size characters

    Args:
        file_path: Path to the markdown file
        chunk_size: Target size for each chunk in characters
        chunk_type: Type of chunks ("docs") for field naming - kept for compatibility

    Returns:
        List of chunk dictionaries with text, source, and title fields
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract title from the first heading or filename
        title_match = re.search(r'^# (.*?)$', content, re.MULTILINE)
        if title_match:
            title = title_match.group(1)
        else:
            title = os.path.basename(file_path).replace('.md', '').replace('_', ' ').title()

        # Split by paragraphs (blank lines)
        paragraphs = re.split(r'\n\s*\n', content)

        chunks = []
        current_chunk = ""
        current_chunk_size = 0

        for para in paragraphs:
            # Skip empty paragraphs
            if not para.strip():
                continue

            para_size = len(para)

            # If paragraph is too big on its own, split it further
            if para_size > chunk_size:
                # Try to split by sentences
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) <= chunk_size:
                        current_chunk += sentence + " "
                        current_chunk_size += len(sentence) + 1
                    else:
                        if current_chunk:
                            chunks.append(_create_chunk_dict(
                                current_chunk.strip(), file_path, title
                            ))
                        current_chunk = sentence + " "
                        current_chunk_size = len(sentence) + 1
            else:
                # If adding this paragraph exceeds the chunk size, start a new chunk
                if current_chunk_size + para_size > chunk_size and current_chunk:
                    chunks.append(_create_chunk_dict(
                        current_chunk.strip(), file_path, title
                    ))
                    current_chunk = para + "\n\n"
                    current_chunk_size = para_size + 2
                else:
                    current_chunk += para + "\n\n"
                    current_chunk_size += para_size + 2

        # Add the last chunk if it's not empty
        if current_chunk:
            chunks.append(_create_chunk_dict(
                current_chunk.strip(), file_path, title
            ))

        return chunks

    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return []


def _create_chunk_dict(text_content: str, file_path: str, title: str) -> Dict[str, Any]:
    """Create a chunk dictionary for PostgreSQL BM25 storage"""
    # Convert absolute path to relative path
    relative_path = os.path.relpath(file_path, start=os.getcwd())

    return {
        "text": text_content,
        "source": relative_path,
        "title": title
    }