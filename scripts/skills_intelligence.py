#!/usr/bin/env python3
"""
Skills Intelligence Script

This script loads OPAL skill documentation from markdown files and indexes them
using ParadeDB BM25 for fast semantic search. No external API dependencies required.

Usage:
    python skills_intelligence.py --help
    python skills_intelligence.py --force  # Clean rebuild
    python skills_intelligence.py          # Incremental update
"""

import asyncio
import logging
import os
import sys
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import asyncpg
from dotenv import load_dotenv

# ANSI color codes for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'

    BG_GREEN = '\033[102m'
    BG_YELLOW = '\033[103m'
    BG_BLUE = '\033[104m'

class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to log messages."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.level_colors = {
            logging.DEBUG: Colors.CYAN,
            logging.INFO: Colors.WHITE,
            logging.WARNING: Colors.YELLOW,
            logging.ERROR: Colors.RED,
            logging.CRITICAL: Colors.RED + Colors.BOLD
        }

        self.event_patterns = {
            'Successfully loaded': Colors.GREEN,
            'Skipping': Colors.YELLOW,
            'Updated': Colors.BLUE + Colors.BOLD,
            'Created': Colors.GREEN + Colors.BOLD,
            'Failed': Colors.RED + Colors.BOLD,
            'Error': Colors.RED + Colors.BOLD,
        }

    def format(self, record):
        message = super().format(record)
        level_color = self.level_colors.get(record.levelno, Colors.WHITE)

        colored_message = message
        for pattern, color in self.event_patterns.items():
            if pattern in message:
                colored_message = colored_message.replace(
                    pattern,
                    f"{color}{pattern}{Colors.RESET}"
                )

        if colored_message == message:
            colored_message = f"{level_color}{message}{Colors.RESET}"

        return colored_message

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SkillsIntelligenceLoader:
    """Loads skill documentation from markdown files into PostgreSQL with BM25 indexing."""

    def __init__(self, skills_dir: str = None):
        self.db_pool = None

        # Find skills directory
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            # Default to skills/ in project root
            script_dir = Path(__file__).parent
            self.skills_dir = script_dir.parent / 'skills'

        if not self.skills_dir.exists():
            raise ValueError(f"Skills directory not found: {self.skills_dir}")

        # Statistics
        self.stats = {
            'skills_found': 0,
            'skills_created': 0,
            'skills_updated': 0,
            'skills_skipped': 0,
            'skills_failed': 0,
        }

        # Force mode flag
        self.force_mode = False

    async def initialize_database(self) -> None:
        """Initialize database connection and ensure schema exists."""
        db_password = os.getenv('SEMANTIC_GRAPH_PASSWORD')
        if not db_password:
            raise ValueError("SEMANTIC_GRAPH_PASSWORD environment variable must be set")

        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'semantic_graph'),
            'user': os.getenv('POSTGRES_USER', 'semantic_graph'),
            'password': db_password
        }

        try:
            self.db_pool = await asyncpg.create_pool(**db_config, min_size=1, max_size=5)
            logger.info("Database connection established")

            # Create schema if it doesn't exist
            await self.ensure_schema_exists()

        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    async def ensure_schema_exists(self) -> None:
        """Ensure the skills intelligence schema exists."""
        script_dir = Path(__file__).parent
        schema_path = script_dir.parent / 'sql' / 'skills_intelligence_schema.sql'

        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        async with self.db_pool.acquire() as conn:
            await conn.execute(schema_sql)
            logger.info("Skills intelligence schema created/verified")

    def parse_skill_frontmatter(self, content: str) -> Dict[str, Any]:
        """
        Parse YAML frontmatter from skill markdown file.

        Expected format:
        ---
        name: skill-name
        description: Skill description text
        category: Aggregation  # optional
        difficulty: intermediate  # optional
        tags: ['opal', 'aggregation', 'statsby']  # optional
        ---
        """
        frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if not match:
            return {}

        frontmatter_text = match.group(1)
        metadata = {}

        # Parse simple YAML (we only need basic key: value and key: [list])
        for line in frontmatter_text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                # Parse lists
                if value.startswith('[') and value.endswith(']'):
                    # Simple list parsing: ['item1', 'item2']
                    items = value[1:-1].split(',')
                    metadata[key] = [item.strip().strip("'\"") for item in items if item.strip()]
                else:
                    # Remove quotes
                    metadata[key] = value.strip('"').strip("'")

        return metadata

    def extract_skill_content(self, content: str) -> str:
        """Extract main content after frontmatter."""
        frontmatter_pattern = r'^---\s*\n.*?\n---\s*\n'
        content_without_frontmatter = re.sub(frontmatter_pattern, '', content, count=1, flags=re.DOTALL)
        return content_without_frontmatter.strip()

    def categorize_skill(self, skill_name: str, description: str, content: str) -> str:
        """Auto-categorize skill based on content analysis."""
        content_lower = (skill_name + ' ' + description + ' ' + content[:500]).lower()

        # Category patterns
        if any(term in content_lower for term in ['aggregate', 'statsby', 'group_by', 'count', 'sum']):
            return 'Aggregation'
        elif any(term in content_lower for term in ['filter', 'search', 'contains', 'match']):
            return 'Filtering'
        elif any(term in content_lower for term in ['tdigest', 'percentile', 'latency', 'duration']):
            return 'Analysis'
        elif any(term in content_lower for term in ['window', 'lag', 'lead', 'row_number']):
            return 'Window Functions'
        elif any(term in content_lower for term in ['join', 'lookup', 'union', 'subquery']):
            return 'Data Combination'
        elif any(term in content_lower for term in ['parse', 'extract', 'regex']):
            return 'Parsing'
        elif any(term in content_lower for term in ['timechart', 'time-series', 'temporal']):
            return 'Time Series'
        elif any(term in content_lower for term in ['interval', 'span', 'duration']):
            return 'Intervals'
        elif any(term in content_lower for term in ['resource', 'reference', 'table']):
            return 'Resources'
        else:
            return 'General'

    def detect_difficulty(self, content: str) -> str:
        """Detect skill difficulty based on content complexity."""
        content_lower = content.lower()

        # Advanced indicators
        advanced_terms = ['subquery', 'union', 'window()', 'tdigest_combine', 'nested', 'complex']
        if any(term in content_lower for term in advanced_terms):
            return 'advanced'

        # Beginner indicators
        if any(term in content_lower for term in ['basic', 'simple', 'introduction', 'getting started']):
            return 'beginner'

        # Default to intermediate
        return 'intermediate'

    def extract_tags(self, skill_name: str, description: str, content: str) -> List[str]:
        """Extract relevant tags from skill content."""
        tags = set()

        # Add skill name parts as tags
        name_parts = skill_name.replace('-', ' ').replace('_', ' ').split()
        tags.update(name_parts)

        # Common OPAL verbs and functions
        opal_keywords = [
            'statsby', 'filter', 'make_col', 'timechart', 'window', 'aggregate',
            'align', 'lookup', 'union', 'join', 'parse', 'extract_regex',
            'percentile', 'tdigest', 'group_by', 'sort', 'limit', 'topk',
            'contains', 'count', 'sum', 'avg', 'min', 'max'
        ]

        content_lower = (description + ' ' + content[:1000]).lower()
        for keyword in opal_keywords:
            if keyword in content_lower:
                tags.add(keyword)

        return sorted(list(tags))[:15]  # Limit to 15 most relevant tags

    async def load_skill_file(self, skill_path: Path) -> Optional[Dict[str, Any]]:
        """Load and parse a single skill markdown file."""
        try:
            with open(skill_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse frontmatter
            metadata = self.parse_skill_frontmatter(content)

            # Extract content
            skill_content = self.extract_skill_content(content)

            # Get skill info
            skill_name = metadata.get('name', skill_path.parent.name)
            description = metadata.get('description', 'OPAL skill documentation')

            # Auto-categorize if not specified
            category = metadata.get('category') or self.categorize_skill(skill_name, description, skill_content)

            # Auto-detect difficulty if not specified
            difficulty = metadata.get('difficulty') or self.detect_difficulty(skill_content)

            # Extract or use provided tags
            tags = metadata.get('tags', [])
            if not tags:
                tags = self.extract_tags(skill_name, description, skill_content)

            return {
                'skill_id': skill_name,
                'skill_name': skill_name.replace('-', ' ').replace('_', ' ').title(),
                'description': description,
                'content': skill_content,
                'category': category,
                'tags': tags,
                'difficulty': difficulty,
            }

        except Exception as e:
            logger.error(f"Failed to load skill file {skill_path}: {e}")
            return None

    async def check_skill_needs_update(self, skill_id: str) -> bool:
        """Check if a skill needs to be updated."""
        if self.force_mode:
            return True

        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchrow(
                    "SELECT updated_at FROM skills_intelligence WHERE skill_id = $1",
                    skill_id
                )

                if not result:
                    return True  # New skill

                # Check if updated recently (within 1 hour)
                updated_at = result['updated_at']
                hours_since_update = (datetime.now() - updated_at).total_seconds() / 3600

                if hours_since_update < 1:
                    logger.debug(f"Skipping {skill_id} - updated {hours_since_update:.1f} hours ago")
                    self.stats['skills_skipped'] += 1
                    return False

                return True

        except Exception as e:
            logger.warning(f"Error checking update status for {skill_id}: {e}")
            return True  # Update on error

    async def store_skill(self, skill_data: Dict[str, Any]) -> None:
        """Store or update skill in database."""
        try:
            async with self.db_pool.acquire() as conn:
                # Check if skill exists
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM skills_intelligence WHERE skill_id = $1)",
                    skill_data['skill_id']
                )

                if exists:
                    # Update existing
                    await conn.execute("""
                        UPDATE skills_intelligence
                        SET skill_name = $2,
                            description = $3,
                            content = $4,
                            category = $5,
                            tags = $6,
                            difficulty = $7,
                            updated_at = NOW()
                        WHERE skill_id = $1
                    """,
                        skill_data['skill_id'],
                        skill_data['skill_name'],
                        skill_data['description'],
                        skill_data['content'],
                        skill_data['category'],
                        skill_data['tags'],
                        skill_data['difficulty']
                    )
                    self.stats['skills_updated'] += 1
                    logger.info(f"Updated skill: {skill_data['skill_name']}")
                else:
                    # Insert new
                    await conn.execute("""
                        INSERT INTO skills_intelligence (
                            skill_id, skill_name, description, content,
                            category, tags, difficulty
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                        skill_data['skill_id'],
                        skill_data['skill_name'],
                        skill_data['description'],
                        skill_data['content'],
                        skill_data['category'],
                        skill_data['tags'],
                        skill_data['difficulty']
                    )
                    self.stats['skills_created'] += 1
                    logger.info(f"Created skill: {skill_data['skill_name']}")

        except Exception as e:
            logger.error(f"Failed to store skill {skill_data['skill_id']}: {e}")
            self.stats['skills_failed'] += 1

    async def load_all_skills(self) -> None:
        """Load all skills from the skills directory."""
        logger.info("")
        logger.info("╔═══════════════════════════════════════════════════════════════╗")
        logger.info("║              📚 Skills Intelligence Loader                   ║")
        logger.info("║                                                               ║")
        logger.info("║  Loading OPAL skill documentation for BM25 search           ║")
        if self.force_mode:
            logger.info("║                    🧹 FORCE MODE ENABLED 🧹                    ║")
        logger.info("╚═══════════════════════════════════════════════════════════════╝")
        logger.info("")
        logger.info(f"🔍 Scanning skills directory: {self.skills_dir}")

        # Find all SKILL.md files
        skill_files = list(self.skills_dir.glob('*/SKILL.md'))

        if not skill_files:
            logger.warning(f"No skill files found in {self.skills_dir}")
            return

        self.stats['skills_found'] = len(skill_files)
        logger.info(f"📝 Found {len(skill_files)} skill files")

        # Process each skill
        for i, skill_file in enumerate(skill_files, 1):
            logger.info(f"Processing {i}/{len(skill_files)}: {skill_file.parent.name}")

            # Check if update needed
            if not await self.check_skill_needs_update(skill_file.parent.name):
                continue

            # Load skill data
            skill_data = await self.load_skill_file(skill_file)

            if skill_data:
                # Store in database
                await self.store_skill(skill_data)
            else:
                self.stats['skills_failed'] += 1

        logger.info("Skills loading completed")
        self.print_statistics()

    def print_statistics(self) -> None:
        """Print loading statistics."""
        logger.info("")
        logger.info("╔═══════════════════════════════════════════════════════════════╗")
        logger.info("║                    📊 Loading Statistics                     ║")
        logger.info("╠═══════════════════════════════════════════════════════════════╣")
        logger.info(f"║ Skills found: {self.stats['skills_found']:>43} ║")
        logger.info(f"║ Skills created: {self.stats['skills_created']:>41} ║")
        logger.info(f"║ Skills updated: {self.stats['skills_updated']:>41} ║")
        logger.info(f"║ Skills skipped: {self.stats['skills_skipped']:>41} ║")
        logger.info(f"║ Skills failed: {self.stats['skills_failed']:>42} ║")
        logger.info("╚═══════════════════════════════════════════════════════════════╝")
        logger.info("")

    async def clear_database(self) -> None:
        """Clear all skills for fresh start."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE skills_intelligence RESTART IDENTITY CASCADE")
            logger.info("🧹 Cleared all skills from database")

            try:
                await conn.execute("VACUUM ANALYZE skills_intelligence")
                logger.info("🧹 Refreshed indexes and statistics")
            except Exception as e:
                logger.warning(f"Failed to refresh indexes: {e} (non-critical)")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.db_pool:
            await self.db_pool.close()


async def main():
    parser = argparse.ArgumentParser(description="Load OPAL skills for BM25 search")
    parser.add_argument('--skills-dir', type=str, help='Path to skills directory')
    parser.add_argument('--force', action='store_true', help='Force clean database and reload all skills')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    args = parser.parse_args()

    # Configure colored logging
    handler = logging.StreamHandler()
    formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    loader = SkillsIntelligenceLoader(skills_dir=args.skills_dir)
    loader.force_mode = args.force

    try:
        await loader.initialize_database()

        if args.force:
            logger.info("🧹 Force mode enabled - clearing skills database...")
            await loader.clear_database()

        await loader.load_all_skills()

    except KeyboardInterrupt:
        logger.info("Loading interrupted by user")
    except Exception as e:
        logger.error(f"Loading failed: {e}")
        raise
    finally:
        await loader.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
