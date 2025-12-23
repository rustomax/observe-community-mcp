"""
API Error Enhancement Module

Provides contextual help for Observe API errors by pattern matching
and generating helpful suggestions with links to relevant tools and documentation.
"""

import re
from typing import Optional


# Error pattern catalog with enhancement suggestions
ERROR_PATTERNS = [
    {
        "name": "non_existent_field",
        "pattern": r'the field "([^"]+)" does not exist among fields \[([^\]]+)\]',
        "priority": "high",
        "description": "Field doesn't exist in dataset"
    },
    {
        "name": "metric_outside_align",
        "pattern": r'Please only use metric selection function "m" in "align" verb',
        "priority": "high",
        "description": "m() function used outside align verb"
    },
    {
        "name": "missing_function_parameter",
        "pattern": r'"([^"]+)" parameter "([^"]+)" has no matching argument',
        "priority": "medium",
        "description": "Function called without required parameter"
    },
    {
        "name": "aggregate_wrong_context",
        "pattern": r'aggregate function "([^"]+)" is not accepted in the current context.*window\(\)',
        "priority": "medium",
        "description": "Aggregate function used in wrong context"
    },
    {
        "name": "type_mismatch",
        "pattern": r'"([^"]+)" argument (\d+) \("([^"]+)"\) must be of type ([^,]+), but is currently of type (\w+)',
        "priority": "medium",
        "description": "Function argument type mismatch"
    },
    {
        "name": "dataset_reference_without_join",
        "pattern": r'must be accessed with a join verb',
        "priority": "high",
        "description": "Dataset reference (@alias) without proper join setup"
    },
    {
        "name": "invalid_dataset_id",
        "pattern": r'Failed to parse.*ObjectId.*illegal value',
        "priority": "medium",
        "description": "Invalid dataset ID format"
    },
]


def enhance_field_error(match, query: str, dataset_id: str, schema_info: Optional[str] = None) -> str:
    """Enhancement for non-existent field errors."""
    field_name = match.group(1)
    available_fields_raw = match.group(2)

    # Parse and format the available fields for better readability
    fields = [f.strip() for f in available_fields_raw.split(',')]

    # Check if this is a metrics query context
    is_metrics_query = 'align' in query.lower() or 'm(' in query or 'metric' in query.lower()
    has_labels_field = 'labels' in fields

    # Check if the missing field looks like a dimension (common metric dimension patterns)
    dimension_patterns = ['_name', '_id', '_uid', 'namespace', 'cluster', 'pod', 'node', 'service', 'host', 'container']
    looks_like_dimension = any(pattern in field_name.lower() for pattern in dimension_patterns)

    # Detect if filtering after aggregation
    query_lower = query.lower()
    has_align = 'align' in query_lower
    filter_after_align = False
    if has_align:
        # Simple check: if filter appears after align in the query
        align_pos = query_lower.find('align')
        filter_pos = query_lower.find('filter')
        if filter_pos > align_pos >= 0:
            filter_after_align = True

    # Format fields in a more readable way (group them for easier scanning)
    if len(fields) <= 10:
        # Show all fields as a list
        fields_formatted = '\n   '.join([f'• {field}' for field in fields])
        fields_display = f"\n\n📋 Available Fields in Dataset:\n   {fields_formatted}"
    else:
        # Show first 10 and count
        first_ten = '\n   '.join([f'• {field}' for field in fields[:10]])
        fields_display = f"\n\n📋 Available Fields in Dataset ({len(fields)} total, showing first 10):\n   {first_ten}\n   ... and {len(fields) - 10} more"

    help_text = (
        f"\n\n💡 Contextual Help:"
        f"\n• Field '{field_name}' doesn't exist in this dataset"
        f"{fields_display}"
    )

    # Provide context-specific guidance
    if is_metrics_query and looks_like_dimension and filter_after_align and has_labels_field:
        # This is likely the metrics aggregation dimension issue
        help_text += (
            f"\n\n🎯 Metrics Query Issue Detected:"
            f"\n\n⚠️ You're trying to filter on dimension field '{field_name}' after aggregation."
            f"\nAfter align/aggregate, dimension fields are no longer directly accessible."
            f"\n\nTwo solutions:"
            f"\n\n✅ Option 1: Filter BEFORE aggregation (recommended)"
            f"\n   filter {field_name} ~ \"your-value\""
            f"\n   | align 1m, value:avg(m(\"metric_name\"))"
            f"\n"
            f"\n✅ Option 2: Group by the dimension, then access via labels"
            f"\n   align 1m, value:avg(m(\"metric_name\")), group_by({field_name})"
            f"\n   | filter labels.{field_name} ~ \"your-value\""
            f"\n"
            f"\n📖 Learn more about metrics queries:"
            f"\n   learn_observe_skill(\"OPAL metrics align aggregate pattern\")"
        )
    elif is_metrics_query and has_labels_field:
        # Generic metrics guidance
        help_text += (
            f"\n\n🎯 Metrics Query Tip:"
            f"\n• After align/aggregate, dimensions move to the 'labels' object"
            f"\n• Use discover_context() to see available dimensions for this metric"
            f"\n• Filter on dimensions BEFORE aggregation for best results"
        )

    # If schema info was provided, include it
    if schema_info:
        help_text += f"\n\n📋 Complete Schema Information:\n{schema_info}"
    else:
        # General discovery guidance
        if is_metrics_query:
            help_text += (
                f"\n\n🔍 To see metric details (dimensions, value ranges, examples), run:"
                f"\n   discover_context(metric_name=\"{field_name}\")"
            )
        else:
            help_text += (
                f"\n\n🔍 To see complete field details (types, samples, nested paths), run:"
                f"\n   discover_context(dataset_id=\"{dataset_id}\")"
            )

        # Common issues (only if not already covered by metrics-specific guidance)
        if not (is_metrics_query and looks_like_dimension and filter_after_align):
            help_text += (
                f"\n\n💡 Common Issues:"
                f"\n   • Nested fields need quotes: resource_attributes.\"k8s.pod.name\""
                f"\n   • Logs use 'timestamp', spans use 'start_time'/'end_time'"
            )
            if not is_metrics_query:
                help_text += f"\n   • After align/aggregate, dimensions move to 'labels' object"

    return help_text


def enhance_metric_error(match, query: str, dataset_id: str) -> str:
    """Enhancement for metric function outside align verb."""
    return (
        "\n\n💡 Contextual Help:"
        "\n• Metrics require a specific pattern: align → m() → aggregate"
        "\n• Example:"
        "\n  align 5m, value:sum(m(\"metric_name\"))"
        "\n  | aggregate total:sum(value), group_by(service_name)"
        "\n  | filter total > 100"
        "\n"
        "\n• Common mistake: Using m() in filter or statsby directly"
        "\n• Documentation: https://docs.observeinc.com/en/latest/content/query-language-reference/verbs/align.html"
    )


def enhance_missing_parameter_error(match, query: str, dataset_id: str) -> str:
    """Enhancement for missing function parameter errors."""
    func_name = match.group(1)
    param_name = match.group(2)

    return (
        f"\n\n💡 Contextual Help:"
        f"\n• Function '{func_name}()' is missing required parameter '{param_name}'"
        f"\n• Check function signature and examples:"
        f"\n  https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALFunctions.html"
        f"\n"
        f"\n• Common OPAL functions:"
        f"\n  - contains(haystack, needle) - check if string contains substring"
        f"\n  - if(condition, true_value, false_value) - conditional expression"
        f"\n  - string(value) - convert to string type"
        f"\n  - count() - count rows (no parameters in aggregate context)"
    )


def enhance_aggregate_context_error(match, query: str, dataset_id: str) -> str:
    """Enhancement for aggregate function in wrong context."""
    func_name = match.group(1)

    return (
        f"\n\n💡 Contextual Help:"
        f"\n• Aggregate function '{func_name}()' cannot be used in filter"
        f"\n• Use aggregate functions in these contexts:"
        f"\n  - statsby: statsby count(), group_by(service)"
        f"\n  - timechart: timechart 5m, count()"
        f"\n  - window(): window(count(1), group_by(field), frame(back:5m))"
        f"\n"
        f"\n• For conditional counting, use this pattern:"
        f"\n  make_col is_error:if(contains(body, \"error\"), 1, 0)"
        f"\n  | statsby error_count:sum(is_error), group_by(service)"
        f"\n"
        f"\n• Documentation: https://docs.observeinc.com/en/latest/content/query-language-reference/function-categories.html"
    )


def enhance_type_mismatch_error(match, query: str, dataset_id: str) -> str:
    """Enhancement for type mismatch errors."""
    func_name = match.group(1)
    arg_num = match.group(2)
    param_name = match.group(3)
    expected_type = match.group(4)
    actual_type = match.group(5)

    return (
        f"\n\n💡 Contextual Help:"
        f"\n• Function '{func_name}()' expects {expected_type} for parameter '{param_name}', but got {actual_type}"
        f"\n• Use type conversion functions:"
        f"\n  - string(value) - convert to string"
        f"\n  - int64(value) - convert to integer"
        f"\n  - float64(value) - convert to float"
        f"\n  - timestamp_ms(value) - convert milliseconds to timestamp"
        f"\n"
        f"\n• Example fix:"
        f"\n  make_col converted:string({param_name})"
        f"\n  | make_col result:{func_name}(converted)"
        f"\n"
        f"\n• Documentation: https://docs.observeinc.com/en/latest/content/query-language-reference/function-categories.html"
    )


def enhance_join_error(match, query: str, dataset_id: str) -> str:
    """Enhancement for dataset reference without join."""
    return (
        "\n\n💡 Contextual Help:"
        "\n• You're trying to reference another dataset with @ syntax"
        "\n• This requires proper multi-dataset setup:"
        "\n"
        "\n  execute_opal_query("
        "\n    query='join on(field=@alias.field), new_col:@alias.column',"
        "\n    primary_dataset_id='123',"
        "\n    secondary_dataset_ids='[\"456\"]',"
        "\n    dataset_aliases='{\"alias\": \"456\"}'"
        "\n  )"
        "\n"
        "\n• Steps:"
        "\n  1. Provide secondary_dataset_ids as JSON array: '[\"456\"]'"
        "\n  2. Map aliases with dataset_aliases: '{\"alias\": \"456\"}'"
        "\n  3. Use join verb in query: 'join on(field=@alias.field)'"
        "\n"
        "\n• Documentation: https://docs.observeinc.com/en/latest/content/query-language-reference/verbs/join.html"
    )


def enhance_invalid_dataset_id_error(match, query: str, dataset_id: str) -> str:
    """Enhancement for invalid dataset ID format."""
    return (
        "\n\n💡 Contextual Help:"
        "\n• Invalid dataset ID format"
        "\n• Dataset IDs must be numeric strings like '42161740'"
        "\n• To find valid dataset IDs:"
        "\n"
        "\n  discover_context(query='your search term')"
        "\n"
        "\n• Examples:"
        "\n  - discover_context('kubernetes logs')"
        "\n  - discover_context('error metrics')"
        "\n  - discover_context(dataset_name='Kubernetes Explorer/Kubernetes Logs')"
    )


# Mapping of pattern names to enhancement functions
ENHANCEMENT_FUNCTIONS = {
    "non_existent_field": enhance_field_error,
    "metric_outside_align": enhance_metric_error,
    "missing_function_parameter": enhance_missing_parameter_error,
    "aggregate_wrong_context": enhance_aggregate_context_error,
    "type_mismatch": enhance_type_mismatch_error,
    "dataset_reference_without_join": enhance_join_error,
    "invalid_dataset_id": enhance_invalid_dataset_id_error,
}


def enhance_api_error(error_message: str, query: str, dataset_id: Optional[str] = None, schema_info: Optional[str] = None) -> str:
    """
    Enhance Observe API error messages with contextual help.

    Args:
        error_message: Original error message from Observe API
        query: The OPAL query that caused the error
        dataset_id: Dataset ID used in the query (optional)
        schema_info: Pre-fetched schema information to include in error (optional)

    Returns:
        Enhanced error message with actionable suggestions

    Examples:
        >>> enhance_api_error(
        ...     'the field "message" does not exist among fields [body, timestamp]',
        ...     'filter message ~ error',
        ...     '42161740'
        ... )
        'the field "message" does not exist among fields [body, timestamp]\\n\\n💡 Contextual Help: ...'
    """
    if dataset_id is None:
        dataset_id = "DATASET_ID"

    # Try to match error patterns and add suggestions
    for pattern_info in ERROR_PATTERNS:
        match = re.search(pattern_info["pattern"], error_message, re.IGNORECASE | re.DOTALL)
        if match:
            enhancement_func = ENHANCEMENT_FUNCTIONS.get(pattern_info["name"])
            if enhancement_func:
                # Pass schema_info to enhancement function (only field error uses it)
                if pattern_info["name"] == "non_existent_field":
                    suggestion = enhancement_func(match, query, dataset_id, schema_info)
                else:
                    suggestion = enhancement_func(match, query, dataset_id)
                return error_message + suggestion
            break

    # No enhancement found, return original error
    return error_message
