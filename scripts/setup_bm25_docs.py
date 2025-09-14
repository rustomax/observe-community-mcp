#!/usr/bin/env python3
"""
One-click BM25 documentation setup

This script automatically handles everything needed for BM25 documentation search:
- Creates database schema
- Attempts to install BM25 extension (with graceful fallback)
- Indexes documentation
- Validates the setup

Just like the original populate_docs_index.py, but for PostgreSQL BM25.
"""

import os
import sys
import asyncio
import argparse
from dotenv import load_dotenv

# Add parent directory to Python path so we can import src modules
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

# Load environment variables
load_dotenv()

import asyncpg
from src.postgres.document_utils import find_markdown_files, chunk_markdown
from src.logging import get_logger

logger = get_logger('BM25_SETUP')

# Configuration
DOCS_DIR = os.getenv("OBSERVE_DOCS_DIR", "observe-docs")
DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER', 'semantic_graph')}:{os.getenv('SEMANTIC_GRAPH_PASSWORD', 'g83hbeyB32792r3Gsjnfwe0ihf2')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'semantic_graph')}"


async def setup_database_schema(conn: asyncpg.Connection) -> bool:
    """Create database schema - returns True if successful"""
    try:
        logger.info("creating database schema")

        # Create the main table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS documentation_chunks (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                chunk_size INTEGER,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create basic indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_documentation_chunks_source ON documentation_chunks(source)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_documentation_chunks_title ON documentation_chunks(title)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_documentation_chunks_created_at ON documentation_chunks(created_at)")

        # Create trigger function for updated_at
        await conn.execute("""
            CREATE OR REPLACE FUNCTION update_documentation_chunks_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                NEW.chunk_size = LENGTH(NEW.text);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)

        # Create triggers
        await conn.execute("DROP TRIGGER IF EXISTS trg_documentation_chunks_updated_at ON documentation_chunks")
        await conn.execute("DROP TRIGGER IF EXISTS trg_documentation_chunks_insert ON documentation_chunks")

        await conn.execute("""
            CREATE TRIGGER trg_documentation_chunks_updated_at
                BEFORE UPDATE ON documentation_chunks
                FOR EACH ROW
                EXECUTE FUNCTION update_documentation_chunks_updated_at()
        """)

        await conn.execute("""
            CREATE TRIGGER trg_documentation_chunks_insert
                BEFORE INSERT ON documentation_chunks
                FOR EACH ROW
                EXECUTE FUNCTION update_documentation_chunks_updated_at()
        """)

        logger.info("✅ database schema created successfully")
        return True

    except Exception as e:
        logger.error(f"❌ failed to create database schema | error:{e}")
        return False


async def setup_bm25_extension(conn: asyncpg.Connection) -> bool:
    """Try to setup BM25 extension - returns True if BM25 available"""
    try:
        logger.info("checking for BM25 extension")

        # Check if extension already exists
        ext_exists = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_search')")

        if ext_exists:
            logger.info("✅ BM25 extension already installed")
        else:
            # Try to create extension
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
                logger.info("✅ BM25 extension installed successfully")
                ext_exists = True
            except Exception as e:
                logger.warning(f"⚠️  BM25 extension not available | error:{e}")
                logger.info("📝 falling back to PostgreSQL full-text search (still very good!)")
                ext_exists = False

        # Create appropriate search index
        if ext_exists:
            # Create BM25 index
            await conn.execute("DROP INDEX IF EXISTS idx_documentation_chunks_bm25")
            await conn.execute("DROP INDEX IF EXISTS idx_documentation_chunks_fts")

            await conn.execute("""
                CREATE INDEX idx_documentation_chunks_bm25
                ON documentation_chunks
                USING bm25 (id, text, title) WITH (key_field='id')
            """)
            logger.info("✅ BM25 search index created")
        else:
            # Create full-text search index as fallback
            await conn.execute("DROP INDEX IF EXISTS idx_documentation_chunks_bm25")
            await conn.execute("DROP INDEX IF EXISTS idx_documentation_chunks_fts")

            await conn.execute("""
                CREATE INDEX idx_documentation_chunks_fts
                ON documentation_chunks
                USING gin(to_tsvector('english', text || ' ' || title))
            """)
            logger.info("✅ full-text search index created (fallback)")

        return ext_exists

    except Exception as e:
        logger.error(f"❌ failed to setup search extension | error:{e}")
        return False


async def clear_existing_data(conn: asyncpg.Connection) -> int:
    """Clear existing documentation chunks"""
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM documentation_chunks") or 0
        if count > 0:
            await conn.execute("DELETE FROM documentation_chunks")
            logger.info(f"🗑️  cleared {count} existing chunks")
        return count
    except Exception as e:
        logger.error(f"error clearing existing data | error:{e}")
        return 0


async def index_documents(conn: asyncpg.Connection, docs_dir: str, batch_size: int = 100) -> int:
    """Index documents using the same logic as Pinecone"""
    try:
        logger.info(f"📚 indexing documents from: {docs_dir}")

        # Find markdown files (reuse Pinecone logic)
        docs_dir = os.path.abspath(docs_dir)
        md_files = find_markdown_files(docs_dir)

        if not md_files:
            logger.error(f"❌ no markdown files found in: {docs_dir}")
            return 0

        logger.info(f"📄 found {len(md_files)} markdown files")

        # Process files into chunks (reuse Pinecone chunking logic)
        all_chunks = []
        for file_path in md_files:
            try:
                chunks = chunk_markdown(file_path, chunk_type="docs")
                all_chunks.extend(chunks)
            except Exception as e:
                logger.error(f"error processing {os.path.basename(file_path)} | error:{e}")

        if not all_chunks:
            logger.error("❌ no chunks generated from documents")
            return 0

        logger.info(f"📦 generated {len(all_chunks)} chunks")

        # Insert chunks in batches
        total_inserted = 0
        for i in range(0, len(all_chunks), batch_size):
            batch_chunks = all_chunks[i:i+batch_size]

            # Prepare batch data
            batch_data = [(chunk["text"], chunk["source"], chunk["title"], len(chunk["text"])) for chunk in batch_chunks]

            # Batch insert
            await conn.executemany("""
                INSERT INTO documentation_chunks (text, source, title, chunk_size)
                VALUES ($1, $2, $3, $4)
            """, batch_data)

            total_inserted += len(batch_chunks)
            logger.info(f"📥 indexed batch {i//batch_size + 1}/{(len(all_chunks)-1)//batch_size + 1} ({total_inserted} total chunks)")

        return total_inserted

    except Exception as e:
        logger.error(f"❌ failed to index documents | error:{e}")
        return 0


async def test_search(conn: asyncpg.Connection, has_bm25: bool) -> bool:
    """Test search functionality"""
    try:
        logger.info("🔍 testing search functionality")

        test_query = "OPAL filter"

        if has_bm25:
            # Test BM25 search
            results = await conn.fetch("""
                SELECT title, source, paradedb.score(id) as score
                FROM documentation_chunks
                WHERE text @@@ $1 OR title @@@ $1
                ORDER BY paradedb.score(id) DESC
                LIMIT 3
            """, test_query)
            search_type = "BM25"
        else:
            # Test full-text search
            results = await conn.fetch("""
                SELECT title, source,
                       ts_rank(to_tsvector('english', text), plainto_tsquery('english', $1)) as score
                FROM documentation_chunks
                WHERE to_tsvector('english', text) @@ plainto_tsquery('english', $1)
                ORDER BY score DESC
                LIMIT 3
            """, test_query)
            search_type = "Full-Text"

        if results:
            logger.info(f"✅ {search_type} search working! Found {len(results)} results for '{test_query}'")
            for i, row in enumerate(results, 1):
                logger.info(f"   {i}. {row['title']} (score: {row['score']:.3f})")
            return True
        else:
            logger.warning(f"⚠️  search functional but no results for test query '{test_query}'")
            return True  # Still consider successful if search works

    except Exception as e:
        logger.error(f"❌ search test failed | error:{e}")
        return False


async def get_final_stats(conn: asyncpg.Connection, has_bm25: bool) -> dict:
    """Get final statistics"""
    try:
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_chunks,
                COUNT(DISTINCT source) as total_documents,
                AVG(chunk_size) as avg_chunk_size,
                MAX(created_at) as last_indexed
            FROM documentation_chunks
        """)

        return {
            "total_chunks": stats['total_chunks'],
            "total_documents": stats['total_documents'],
            "avg_chunk_size": int(stats['avg_chunk_size']) if stats['avg_chunk_size'] else 0,
            "search_type": "BM25" if has_bm25 else "Full-Text",
            "last_indexed": stats['last_indexed']
        }

    except Exception as e:
        logger.error(f"error getting stats | error:{e}")
        return {}


async def main():
    parser = argparse.ArgumentParser(description='One-click BM25 documentation setup')
    parser.add_argument('--docs-dir', type=str, default=DOCS_DIR, help='Directory containing markdown files')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for database inserts')
    args = parser.parse_args()

    print("🚀 Setting up BM25 documentation search...")
    print("")

    # Check if Docker containers are running (for BM25 support)
    import subprocess
    try:
        result = subprocess.run(["docker", "ps"], capture_output=True, text=True, check=True)
        if "observe-semantic-graph" in result.stdout:
            print("✅ Using existing Docker PostgreSQL with BM25 support")
        print("")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # Docker not available or not running

    print("🚀 BM25 Documentation Search Setup")
    print("=" * 50)
    print("This script will automatically:")
    print("  1. Create database schema")
    print("  2. Setup search indexes (BM25 if available)")
    print("  3. Index your documentation")
    print("  4. Test search functionality")
    print("")

    try:
        # Connect to database
        logger.info("connecting to PostgreSQL")
        conn = await asyncpg.connect(DATABASE_URL)

        try:
            # Step 1: Create database schema
            if not await setup_database_schema(conn):
                print("❌ Failed to create database schema")
                return 1

            # Step 2: Setup BM25 extension
            has_bm25 = await setup_bm25_extension(conn)

            # Step 3: Clear existing data
            await clear_existing_data(conn)

            # Step 4: Index documents
            total_chunks = await index_documents(conn, args.docs_dir, args.batch_size)

            if total_chunks == 0:
                print("❌ No documents were indexed")
                return 1

            # Step 5: Test search
            if not await test_search(conn, has_bm25):
                print("❌ Search functionality test failed")
                return 1

            # Step 6: Show final stats
            stats = await get_final_stats(conn, has_bm25)

            print("\n🎉 Setup completed successfully!")
            print("=" * 50)
            print(f"📊 Indexed: {stats['total_chunks']} chunks from {stats['total_documents']} documents")
            print(f"🔍 Search type: {stats['search_type']}")
            print(f"📏 Average chunk size: {stats['avg_chunk_size']} characters")
            print("")
            print("✅ Your get_relevant_docs() MCP tool is now ready to use!")
            print("")

            if has_bm25:
                print("💡 You're using BM25 search - excellent performance for technical docs!")
            else:
                print("💡 Using PostgreSQL full-text search - excellent for technical documentation!")

            print("")
            print("🎉 All done! Your documentation search is ready.")
            print("")
            print("Quick test:")
            print("  python -c \"import asyncio; from src.postgres.doc_search import search_docs_bm25; print(asyncio.run(search_docs_bm25('OPAL filter', 2)))\"")

            return 0

        finally:
            await conn.close()

    except Exception as e:
        print("")
        print("❌ Setup failed. Check the logs above.")
        print("")
        print("Common fixes:")
        print("  1. Ensure PostgreSQL is running")
        print("  2. Check your .env file has correct POSTGRES_* settings")
        print("  3. Verify the docs directory exists: export OBSERVE_DOCS_DIR=/path/to/docs")
        print(f"\nError details: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))