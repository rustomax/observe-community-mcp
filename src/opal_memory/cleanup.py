"""
Cleanup and maintenance functionality for the OPAL Memory System
"""

import asyncio
import sys
from datetime import datetime, timedelta
from typing import Dict, Any

from .queries import cleanup_memory, get_memory_stats, health_check


async def perform_daily_cleanup() -> Dict[str, Any]:
    """
    Perform daily cleanup operations on the memory system.
    This function can be called by a cron job or scheduled task.
    """
    print("Starting daily OPAL memory cleanup...", file=sys.stderr)
    start_time = datetime.utcnow()
    
    try:
        # Check system health first
        health_result = await health_check()
        if not health_result.get("healthy", False):
            return {
                "success": False,
                "error": f"Memory system not healthy: {health_result.get('message', 'Unknown error')}",
                "execution_time": 0
            }
        
        # Get stats before cleanup
        stats_before = await get_memory_stats()
        
        # Perform cleanup (default settings from environment)
        cleanup_result = await cleanup_memory()
        
        # Get stats after cleanup
        stats_after = await get_memory_stats()
        
        end_time = datetime.utcnow()
        total_time = (end_time - start_time).total_seconds()
        
        result = {
            "success": True,
            "cleanup_result": cleanup_result,
            "stats_before": stats_before,
            "stats_after": stats_after,
            "execution_time": total_time,
            "timestamp": end_time.isoformat()
        }
        
        print(f"Daily cleanup completed in {total_time:.2f}s", file=sys.stderr)
        print(f"Removed {cleanup_result.get('total_entries_removed', 0)} entries", file=sys.stderr)
        
        return result
        
    except Exception as e:
        end_time = datetime.utcnow()
        total_time = (end_time - start_time).total_seconds()
        
        error_result = {
            "success": False,
            "error": str(e),
            "execution_time": total_time,
            "timestamp": end_time.isoformat()
        }
        
        print(f"Daily cleanup failed: {e}", file=sys.stderr)
        return error_result


async def perform_maintenance_check() -> Dict[str, Any]:
    """
    Perform a comprehensive maintenance check of the memory system.
    Returns detailed information about system health and recommendations.
    """
    print("Performing OPAL memory system maintenance check...", file=sys.stderr)
    start_time = datetime.utcnow()
    
    try:
        # Health check
        health_result = await health_check()
        
        # Get current stats
        stats = await get_memory_stats()
        
        # Analyze system state and generate recommendations
        recommendations = []
        warnings = []
        
        if stats.get("enabled", False):
            total_queries = stats.get("total_queries", 0)
            
            # Check if system has data
            if total_queries == 0:
                warnings.append("No queries stored in memory system yet")
                recommendations.append("System is ready to start learning from successful queries")
            elif total_queries > 100000:
                warnings.append(f"Large number of stored queries ({total_queries:,})")
                recommendations.append("Consider running cleanup or adjusting retention settings")
            
            # Check age of data
            oldest_entry = stats.get("oldest_entry")
            if oldest_entry:
                try:
                    oldest_date = datetime.fromisoformat(oldest_entry.replace('Z', '+00:00'))
                    days_old = (datetime.utcnow().replace(tzinfo=oldest_date.tzinfo) - oldest_date).days
                    if days_old > 180:  # 6 months
                        warnings.append(f"Oldest entry is {days_old} days old")
                        recommendations.append("Consider running cleanup to remove very old entries")
                except ValueError:
                    pass  # Skip if date parsing fails
            
            # Check dataset distribution
            unique_datasets = stats.get("unique_datasets", 0)
            if unique_datasets > 50:
                recommendations.append("Many datasets detected - memory system is learning broadly")
            elif unique_datasets < 5 and total_queries > 50:
                warnings.append("Queries concentrated in few datasets")
                recommendations.append("Consider using memory system with more diverse datasets")
        
        end_time = datetime.utcnow()
        total_time = (end_time - start_time).total_seconds()
        
        result = {
            "success": True,
            "health": health_result,
            "stats": stats,
            "recommendations": recommendations,
            "warnings": warnings,
            "execution_time": total_time,
            "timestamp": end_time.isoformat()
        }
        
        print(f"Maintenance check completed in {total_time:.2f}s", file=sys.stderr)
        print(f"Found {len(warnings)} warnings and {len(recommendations)} recommendations", file=sys.stderr)
        
        return result
        
    except Exception as e:
        end_time = datetime.utcnow()
        total_time = (end_time - start_time).total_seconds()
        
        error_result = {
            "success": False,
            "error": str(e),
            "execution_time": total_time,
            "timestamp": end_time.isoformat()
        }
        
        print(f"Maintenance check failed: {e}", file=sys.stderr)
        return error_result


async def emergency_cleanup(dataset_id: str = None, max_entries: int = 10000) -> Dict[str, Any]:
    """
    Perform emergency cleanup when the system is overwhelmed.
    More aggressive than daily cleanup.
    
    Args:
        dataset_id: If specified, only clean this dataset
        max_entries: Maximum entries to keep per dataset
    """
    print(f"Performing emergency cleanup (max_entries={max_entries})", file=sys.stderr)
    start_time = datetime.utcnow()
    
    try:
        # More aggressive cleanup settings
        cleanup_result = await cleanup_memory(
            days_old=30,  # Remove anything older than 30 days
            dataset_id=dataset_id,
            max_entries=max_entries
        )
        
        end_time = datetime.utcnow()
        total_time = (end_time - start_time).total_seconds()
        
        result = {
            "success": True,
            "cleanup_type": "emergency",
            "cleanup_result": cleanup_result,
            "parameters": {
                "dataset_id": dataset_id,
                "max_entries": max_entries,
                "days_old": 30
            },
            "execution_time": total_time,
            "timestamp": end_time.isoformat()
        }
        
        print(f"Emergency cleanup completed in {total_time:.2f}s", file=sys.stderr)
        print(f"Removed {cleanup_result.get('total_entries_removed', 0)} entries", file=sys.stderr)
        
        return result
        
    except Exception as e:
        end_time = datetime.utcnow()
        total_time = (end_time - start_time).total_seconds()
        
        error_result = {
            "success": False,
            "error": str(e),
            "execution_time": total_time,
            "timestamp": end_time.isoformat()
        }
        
        print(f"Emergency cleanup failed: {e}", file=sys.stderr)
        return error_result


if __name__ == "__main__":
    """
    Command-line interface for cleanup operations.
    Usage:
        python -m src.opal_memory.cleanup daily
        python -m src.opal_memory.cleanup maintenance
        python -m src.opal_memory.cleanup emergency [dataset_id] [max_entries]
    """
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m src.opal_memory.cleanup <daily|maintenance|emergency>", file=sys.stderr)
        sys.exit(1)
    
    operation = sys.argv[1].lower()
    
    async def main():
        if operation == "daily":
            result = await perform_daily_cleanup()
        elif operation == "maintenance":
            result = await perform_maintenance_check()
        elif operation == "emergency":
            dataset_id = sys.argv[2] if len(sys.argv) > 2 else None
            max_entries = int(sys.argv[3]) if len(sys.argv) > 3 else 10000
            result = await emergency_cleanup(dataset_id, max_entries)
        else:
            print(f"Unknown operation: {operation}", file=sys.stderr)
            sys.exit(1)
        
        print(f"Operation result: {result}")
        
        if not result.get("success", False):
            sys.exit(1)
    
    asyncio.run(main())