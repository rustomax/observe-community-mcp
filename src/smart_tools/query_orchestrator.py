"""
Query orchestrator for smart tools.

Handles the complete workflow for NLP to OPAL query conversion:
1. Get dataset schema information
2. Get relevant documentation
3. Use LLM to generate OPAL query
4. Execute query and handle errors
5. Return actual results
"""

import sys
from typing import Optional, Dict, Any, List, Tuple
from .llm_client import llm_completion
from .config import is_smart_tools_enabled, validate_smart_tools_config


class QueryOrchestrator:
    """Orchestrates the NLP to OPAL query workflow."""
    
    def __init__(self):
        """Initialize the orchestrator."""
        self.max_retries = 3
        
    async def execute_nlp_query(
        self, 
        dataset_id: str, 
        user_request: str,
        time_range: Optional[str] = "1h",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        get_dataset_info_func=None,
        get_relevant_docs_func=None,
        execute_opal_query_func=None
    ) -> str:
        """
        Execute a natural language query request.
        
        Args:
            dataset_id: The ID of the dataset to query
            user_request: Natural language description of what data is wanted
            time_range: Time range for the query
            start_time: Optional start time in ISO format
            end_time: Optional end time in ISO format
            get_dataset_info_func: Function to get dataset schema
            get_relevant_docs_func: Function to get documentation
            execute_opal_query_func: Function to execute OPAL queries
            
        Returns:
            The actual query results or error message
        """
        try:
            print(f"[ORCHESTRATOR] Starting NLP query execution", file=sys.stderr)
            print(f"[ORCHESTRATOR] Dataset: {dataset_id}", file=sys.stderr)
            print(f"[ORCHESTRATOR] Request: {user_request}", file=sys.stderr)
            
            # Step 1: Get dataset schema information
            print(f"[ORCHESTRATOR] Step 1: Getting dataset schema...", file=sys.stderr)
            dataset_info = await get_dataset_info_func(dataset_id)
            print(f"[ORCHESTRATOR] Dataset info retrieved: {len(str(dataset_info))} chars", file=sys.stderr)
            
            # Step 2: Get relevant documentation with targeted OPAL examples
            print(f"[ORCHESTRATOR] Step 2: Getting relevant OPAL documentation...", file=sys.stderr)
            docs = await get_relevant_docs_func(f"OPAL {user_request} examples syntax")
            print(f"[ORCHESTRATOR] Documentation retrieved: {len(str(docs))} chars", file=sys.stderr)
            
            # Step 3: Generate OPAL query using LLM
            query_context = self._build_query_context(
                dataset_id=dataset_id,
                user_request=user_request,
                dataset_info=dataset_info,
                docs=docs,
                time_range=time_range,
                start_time=start_time,
                end_time=end_time
            )
            
            print(f"[ORCHESTRATOR] Step 3: Generating OPAL query with LLM...", file=sys.stderr)
            opal_query = await self._generate_opal_query(query_context)
            print(f"[ORCHESTRATOR] Generated query: {opal_query}", file=sys.stderr)
            
            # Step 4: Execute query with retry logic
            print(f"[ORCHESTRATOR] Step 4: Executing OPAL query...", file=sys.stderr)
            for attempt in range(self.max_retries):
                try:
                    result = await execute_opal_query_func(
                        query=opal_query,
                        dataset_id=dataset_id,
                        time_range=time_range,
                        start_time=start_time,
                        end_time=end_time,
                        row_count=1000,
                        format="csv"
                    )
                    
                    # Check if result indicates an error (even if no exception was thrown)
                    result_str = str(result)
                    if self._is_error_result(result_str):
                        error_message = self._extract_error_message(result_str)
                        print(f"[ORCHESTRATOR] Query failed on attempt {attempt + 1}: {error_message}", file=sys.stderr)
                        
                        if attempt < self.max_retries - 1:
                            # Get more targeted documentation based on the error
                            print(f"[ORCHESTRATOR] Getting error-specific OPAL documentation...", file=sys.stderr)
                            error_docs = await get_relevant_docs_func(self._build_error_docs_query(error_message, user_request))
                            print(f"[ORCHESTRATOR] Error-specific docs retrieved: {len(str(error_docs))} chars", file=sys.stderr)
                            
                            # Retry with error feedback and new docs
                            print(f"[ORCHESTRATOR] Retrying with error feedback and examples...", file=sys.stderr)
                            retry_context = self._build_retry_context(
                                original_context=query_context,
                                failed_query=opal_query,
                                error=error_message,
                                error_docs=error_docs,
                                attempt=attempt + 1
                            )
                            opal_query = await self._generate_opal_query(retry_context)
                            print(f"[ORCHESTRATOR] Retry query {attempt + 2}: {opal_query}", file=sys.stderr)
                            continue
                        else:
                            print(f"[ORCHESTRATOR] Max retries exceeded", file=sys.stderr)
                            return f"Error: Failed to execute query after {self.max_retries} attempts. Last error: {error_message}"
                    else:
                        print(f"[ORCHESTRATOR] Query executed successfully on attempt {attempt + 1}", file=sys.stderr)
                        print(f"[ORCHESTRATOR] Result length: {len(result_str)} chars", file=sys.stderr)
                        return result
                    
                except Exception as e:
                    print(f"[ORCHESTRATOR] Query failed with exception on attempt {attempt + 1}: {str(e)}", file=sys.stderr)
                    
                    if attempt < self.max_retries - 1:
                        # Get more targeted documentation based on the error
                        print(f"[ORCHESTRATOR] Getting error-specific OPAL documentation...", file=sys.stderr)
                        error_docs = await get_relevant_docs_func(self._build_error_docs_query(str(e), user_request))
                        print(f"[ORCHESTRATOR] Error-specific docs retrieved: {len(str(error_docs))} chars", file=sys.stderr)
                        
                        # Retry with error feedback and new docs
                        print(f"[ORCHESTRATOR] Retrying with error feedback and examples...", file=sys.stderr)
                        retry_context = self._build_retry_context(
                            original_context=query_context,
                            failed_query=opal_query,
                            error=str(e),
                            error_docs=error_docs,
                            attempt=attempt + 1
                        )
                        opal_query = await self._generate_opal_query(retry_context)
                        print(f"[ORCHESTRATOR] Retry query {attempt + 2}: {opal_query}", file=sys.stderr)
                    else:
                        print(f"[ORCHESTRATOR] Max retries exceeded", file=sys.stderr)
                        return f"Error: Failed to execute query after {self.max_retries} attempts. Last error: {str(e)}"
            
        except Exception as e:
            error_msg = f"Error in query orchestration: {str(e)}"
            print(f"[ORCHESTRATOR] ERROR: {error_msg}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return error_msg
    
    def _build_query_context(
        self,
        dataset_id: str,
        user_request: str,
        dataset_info: str,
        docs: str,
        time_range: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str]
    ) -> str:
        """Build the context for LLM query generation."""
        
        return f"""Generate an OPAL query for the following request:

USER REQUEST: {user_request}

DATASET INFORMATION:
{dataset_info}

RELEVANT OPAL DOCUMENTATION:
{docs}

QUERY PARAMETERS:
- Dataset ID: {dataset_id}
- Time range: {time_range}
- Start time: {start_time}
- End time: {end_time}

INSTRUCTIONS:
1. Use ONLY the exact field names from the dataset schema above
2. Generate a valid OPAL query that fulfills the user's request
3. Consider the time parameters provided
4. Return ONLY the OPAL query - no explanation, no analysis, no additional text
5. Do not include dataset_id in the query - that will be handled separately

Example format:
filter field_name = "value" | stats count() by service_name

Your OPAL query:"""

    def _build_retry_context(
        self,
        original_context: str,
        failed_query: str,
        error: str,
        error_docs: str,
        attempt: int
    ) -> str:
        """Build context for retry attempts with error feedback and examples."""
        
        return f"""{original_context}

PREVIOUS ATTEMPT {attempt} FAILED:
Query: {failed_query}
Error: {error}

RELEVANT OPAL EXAMPLES AND DOCUMENTATION:
{error_docs}

INSTRUCTIONS:
1. Study the OPAL examples above that show the correct syntax
2. Use ONLY the exact field names from the dataset schema
3. Follow the patterns shown in the documentation examples
4. Generate a corrected OPAL query that fixes the error

Your corrected OPAL query:"""

    def _build_error_docs_query(self, error_message: str, user_request: str) -> str:
        """Build a targeted documentation search query based on the error."""
        error_lower = error_message.lower()
        
        if 'unknown verb "stats"' in error_lower:
            return "OPAL statsby aggregation examples count average sum"
        elif 'unknown verb' in error_lower and 'group' in error_lower:
            return "OPAL collapsekey grouping examples"
        elif 'unknown verb' in error_lower:
            return f"OPAL {user_request} examples syntax verbs"
        elif 'expected' in error_lower:
            return f"OPAL syntax {user_request} examples proper formatting"
        elif 'must be accessed with a join verb' in error_lower:
            return "OPAL filter simple examples basic queries"
        elif 'time' in error_lower or 'timestamp' in error_lower:
            return "OPAL time filtering examples timestamp"
        else:
            return f"OPAL {user_request} working examples syntax"


    async def _generate_opal_query(self, context: str) -> str:
        """Generate OPAL query using LLM."""
        
        system_prompt = """You are an OPAL query generator. Your ONLY job is to generate valid OPAL queries.

RULES:
1. Study the OPAL documentation and examples provided in the context
2. Use ONLY the exact field names from the dataset schema
3. Follow the syntax patterns shown in the documentation examples
4. Generate a single, valid OPAL query that fulfills the request
5. Return ONLY the OPAL query - no explanation, no analysis, no markdown formatting
6. Do not include dataset_id in the query

CRITICAL: Learn from the documentation examples provided. They show you the correct OPAL syntax patterns to follow.

Generate the OPAL query now:"""

        response = await llm_completion(
            system_prompt=system_prompt,
            user_message=context
        )
        
        # Extract just the query from the response
        query = response.strip()
        
        # Remove any markdown formatting if present
        if query.startswith('```'):
            lines = query.split('\n')
            query = '\n'.join(lines[1:-1] if len(lines) > 2 else lines[1:])
        
        return query.strip()

    def _is_error_result(self, result_str: str) -> bool:
        """Check if the result indicates an error."""
        error_indicators = [
            '"ok":false',
            '"message":"',
            'unknown verb',
            'expected',
            'Error:',
            'failed',
            'syntax error',
            '400',
            '500'
        ]
        
        return any(indicator in result_str for indicator in error_indicators)
    
    def _extract_error_message(self, result_str: str) -> str:
        """Extract error message from result."""
        try:
            # Try to parse as JSON first
            import json
            if '"message":"' in result_str:
                # Extract JSON error message
                start = result_str.find('"message":"') + len('"message":"')
                end = result_str.find('"', start)
                if end > start:
                    return result_str[start:end]
            
            # Fallback to extracting any obvious error text
            if 'Error:' in result_str:
                error_start = result_str.find('Error:')
                error_line = result_str[error_start:error_start + 200]
                return error_line.split('\n')[0]
            
            # Return a portion of the result for debugging
            return result_str[:500] if len(result_str) > 500 else result_str
            
        except Exception:
            return result_str[:200]


# Global orchestrator instance
_orchestrator: Optional[QueryOrchestrator] = None


def get_orchestrator() -> QueryOrchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = QueryOrchestrator()
    return _orchestrator


async def execute_orchestrated_nlp_query(
    dataset_id: str,
    user_request: str,
    time_range: Optional[str] = "1h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    get_dataset_info_func=None,
    get_relevant_docs_func=None,
    execute_opal_query_func=None
) -> str:
    """
    Execute an orchestrated NLP query.
    
    This is the main entry point for the new architecture where Python
    handles the workflow and LLM only generates OPAL queries.
    """
    orchestrator = get_orchestrator()
    return await orchestrator.execute_nlp_query(
        dataset_id=dataset_id,
        user_request=user_request,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time,
        get_dataset_info_func=get_dataset_info_func,
        get_relevant_docs_func=get_relevant_docs_func,
        execute_opal_query_func=execute_opal_query_func
    )