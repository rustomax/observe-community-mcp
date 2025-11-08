"""
OPAL Query Validation and Auto-Fixing

Provides comprehensive validation for OPAL queries to catch errors early
and prevent common mistakes. Automatically fixes common patterns and provides
educational feedback to help LLMs learn correct syntax over time.
"""

import re
from typing import Tuple, Optional, List
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of OPAL query validation and transformation."""
    is_valid: bool
    transformed_query: Optional[str] = None  # None if no transformations applied
    transformations: List[str] = None  # Descriptions of transformations
    error_message: Optional[str] = None  # Error if validation failed

    def __post_init__(self):
        if self.transformations is None:
            self.transformations = []


def transform_multi_term_angle_brackets(query: str) -> Tuple[str, List[str]]:
    """
    Auto-fix multi-term angle bracket syntax by converting to explicit OR logic.

    LLMs often write: filter body ~ <error exception fail>
    Assuming OR semantics (any term matches).

    But OPAL interprets this as AND (all terms must match).
    This transformation converts to the assumed OR intent.

    Examples:
        Input:  filter body ~ <error exception>
        Output: filter contains(body, "error") or contains(body, "exception")

        Input:  filter message ~ <fail fatal panic>
        Output: filter contains(message, "fail") or contains(message, "fatal") or contains(message, "panic")

    Returns:
        Tuple of (transformed_query, list_of_transformation_descriptions)
    """
    transformations = []

    # Pattern to match: fieldname ~ <term1 term2 term3 ...>
    # We need to capture:
    # - The field (which could be complex like string(field) or resource_attributes.name)
    # - The operator (~)
    # - The multi-term angle bracket content

    # Match pattern: field name followed by ~ followed by <multiple terms>
    # Field name can be: word, dotted path, or function call like string(field)
    # Terms inside <> cannot contain angle brackets or pipes (to avoid matching across multiple patterns)
    # Use [^<>|]+ to match any chars except < > | , and make it non-greedy with +?
    # Then require at least one space and more content to ensure multi-term
    pattern = r'([\w.()\"]+)\s+~\s+<([^<>|]+)>'

    def replace_func(match):
        field = match.group(1)
        terms_str = match.group(2).strip()
        terms = terms_str.split()

        # Only transform if there are multiple terms (single-term angle brackets are fine in OPAL)
        if len(terms) <= 1:
            return match.group(0)  # Return original, no transformation

        # Build the contains() or chain
        contains_exprs = [f'contains({field}, "{term}")' for term in terms]
        or_chain = ' or '.join(contains_exprs)
        # Wrap in parentheses to ensure correct precedence with pipeline operator
        replacement = f'({or_chain})'

        # Create educational feedback
        terms_preview = ' '.join(terms[:3])
        if len(terms) > 3:
            terms_preview += f" ... ({len(terms)} terms total)"

        transformations.append(
            f"✓ Auto-fix applied: Multi-term angle bracket converted to OR logic\n"
            f"  Original: {match.group(0)}\n"
            f"  Fixed:    {replacement}\n"
            f"  Reason: <{terms_preview}> uses AND semantics in OPAL (all must match).\n"
            f"          Converted to explicit OR for typical intent (any matches).\n"
            f"  Note: Use single-term syntax if you meant AND: filter {field} ~ {terms[0]} and {field} ~ {terms[1]}"
        )

        return replacement

    transformed_query = re.sub(pattern, replace_func, query)

    # Check if any transformations were made
    if transformed_query != query:
        return transformed_query, transformations
    else:
        return query, []


def transform_redundant_time_filters(query: str, time_range: Optional[str] = None) -> Tuple[str, List[str]]:
    """
    Auto-remove redundant timestamp filters when time_range parameter is set.

    LLMs often add explicit timestamp filters even when the time_range parameter
    already constrains the query time window. This creates redundancy and confusion.

    Examples:
        Input:  filter timestamp > @"1 hour ago" | filter body ~ error
        Context: time_range="1h" is set
        Output: filter body ~ error

        Input:  filter body ~ error | filter BUNDLE_TIMESTAMP >= @"2024-01-01" | limit 10
        Context: time_range="7d" is set
        Output: filter body ~ error | limit 10

    Only removes filters when:
    1. time_range parameter is explicitly set
    2. Filter uses common timestamp field names
    3. Filter uses @"..." time expression syntax

    Returns:
        Tuple of (transformed_query, list_of_transformation_descriptions)
    """
    transformations = []

    # Only transform if time_range is actually set
    if not time_range:
        return query, []

    # Common timestamp field names in OPAL/OpenTelemetry
    TIME_FIELDS = [
        'timestamp',
        'BUNDLE_TIMESTAMP',
        'time',
        '@timestamp',
        'event_time',
        'eventTime',
        'observedTimestamp',
        'OBSERVATION_TIME'
    ]

    # Pattern to match timestamp filters with @"..." syntax
    # Matches: filter <time_field> <operator> @"..."
    # Captures the entire filter operation including surrounding whitespace/pipes
    time_field_pattern = '|'.join(TIME_FIELDS)

    # Match patterns:
    # 1. "filter FIELD OPERATOR @"..." |" (filter in middle/start with following pipe)
    # 2. "| filter FIELD OPERATOR @"..."" (filter at end or middle with preceding pipe)
    # Use alternation to handle both cases
    pattern = rf'(?:^\s*|\|\s*)filter\s+({time_field_pattern})\s*([><=!]+)\s*@"[^"]+"\s*(?:\||$)'

    matches = list(re.finditer(pattern, query))

    if not matches:
        return query, []

    # Process matches in reverse order to preserve positions during removal
    transformed_query = query
    for match in reversed(matches):
        field_name = match.group(1)
        operator = match.group(2)
        original_filter = match.group(0)

        # Determine how to remove the filter cleanly
        # Need to handle pipes properly to avoid leaving "| |" or starting with "|"
        start_pos = match.start()
        end_pos = match.end()

        # Check what comes before and after
        before = transformed_query[:start_pos]
        after = transformed_query[end_pos:]

        # Clean up pipes:
        # - If filter starts with "|" and ends with "|", keep one "|" between before/after
        # - If filter is at start (no "|" before), remove trailing "|" if present
        # - If filter is at end (no "|" after), remove preceding "|" if present

        if before.rstrip().endswith('|') or original_filter.lstrip().startswith('|'):
            # Has preceding pipe
            if after.lstrip().startswith('|') or original_filter.rstrip().endswith('|'):
                # Has following pipe - remove filter and keep one pipe
                before_trimmed = before.rstrip()
                if before_trimmed.endswith('|'):
                    before_trimmed = before_trimmed[:-1].rstrip()
                after_trimmed = after.lstrip()
                if after_trimmed.startswith('|'):
                    after_trimmed = after_trimmed[1:].lstrip()

                if before_trimmed and after_trimmed:
                    # Both sides have content, need pipe between them
                    transformed_query = before_trimmed + ' | ' + after_trimmed
                else:
                    # One side is empty, just concatenate
                    transformed_query = before_trimmed + after_trimmed
            else:
                # No following pipe - just remove filter and preceding pipe
                before_trimmed = before.rstrip()
                if before_trimmed.endswith('|'):
                    before_trimmed = before_trimmed[:-1].rstrip()
                transformed_query = before_trimmed + ' ' + after.lstrip()
        else:
            # No preceding pipe (filter at start)
            after_trimmed = after.lstrip()
            if after_trimmed.startswith('|'):
                after_trimmed = after_trimmed[1:].lstrip()
            transformed_query = before + after_trimmed

        # Create feedback for this removal
        transformations.append(
            f"✓ Auto-fix applied: Redundant timestamp filter removed\n"
            f"  Removed: filter {field_name} {operator} @\"...\"\n"
            f"  Reason: The time_range=\"{time_range}\" parameter already constrains the query time window.\n"
            f"          Explicit timestamp filters are redundant and can cause confusion.\n"
            f"  Note: To narrow the time window beyond time_range, you can still add timestamp filters,\n"
            f"        but in most cases the time_range parameter is sufficient."
        )

    return transformed_query, transformations


def validate_opal_query_structure(query: str, time_range: Optional[str] = None) -> ValidationResult:
    """
    Validate OPAL query structure and apply auto-fix transformations.

    This performs:
    1. Auto-fix transformations for common LLM mistakes
    2. Structural validation without full semantic parsing
    3. Educational feedback on what was changed and why

    Transformations applied:
    - Multi-term angle brackets: <error exception> → contains() OR logic
    - Redundant time filters: Removes timestamp filters when time_range is set

    Validation checks:
    - Validates all verbs in piped sequences against whitelist
    - Checks balanced delimiters (prevents malformed queries)
    - Enforces complexity limits (prevents DoS)

    The Observe API remains the authoritative validator for full semantics.

    Args:
        query: OPAL query string to validate and transform
        time_range: Optional time range parameter (e.g., "1h", "24h") - if set, redundant time filters will be removed

    Returns:
        ValidationResult with:
        - is_valid: Whether query passed validation
        - transformed_query: Auto-fixed query (None if no changes)
        - transformations: List of transformation descriptions
        - error_message: Error details if validation failed
    """
    all_transformations = []

    # Apply transformations before validation
    # Transform 1: Multi-term angle brackets
    query, angle_bracket_transforms = transform_multi_term_angle_brackets(query)
    all_transformations.extend(angle_bracket_transforms)

    # Transform 2: Redundant time filters (when time_range is set)
    query, time_filter_transforms = transform_redundant_time_filters(query, time_range)
    all_transformations.extend(time_filter_transforms)

    # Complete list of OPAL functions (288 functions across 11 categories)
    ALLOWED_FUNCTIONS = {
        'abs', 'any', 'any_not_null', 'append_item', 'arccos_deg', 'arccos_rad',
        'asc', 'desc',  # Sort direction functions
        'arcsin_deg', 'arcsin_rad', 'arctan2_deg', 'arctan2_rad', 'arctan_deg',
        'arctan_rad', 'array_agg', 'array_concat', 'array_contains', 'array_flatten',
        'array_length', 'atoi', 'avg', 'base64decode', 'base64encode', 'bool', 'cast',
        'cbrt', 'ceil', 'coalesce', 'concat', 'contains', 'cos_deg', 'cos_rad', 'cosh',
        'count', 'count_distinct', 'count_distinct_exact', 'deriv', 'distinct_count',
        'duration', 'duration_hr', 'duration_min', 'duration_ms', 'duration_ns',
        'duration_sec', 'duration_us', 'ends_with', 'exp', 'extract_all', 'filter_index',
        'find_index', 'first', 'firstnotnull', 'float64', 'floor', 'fold_any',
        'fold_interval', 'format_date', 'format_duration', 'format_url', 'frac', 'from_base64',
        'from_epochms', 'from_epochns', 'from_hex', 'from_json', 'from_nanoseconds',
        'from_proto_timestamp', 'from_url', 'group_by', 'hash', 'host', 'if', 'int', 'int64',
        'ipaddr', 'ipsubnet', 'is_ipv4', 'is_ipv6', 'is_null', 'is_private_ip', 'is_url',
        'json_extract', 'json_group_object', 'lag', 'last', 'lastnotnull', 'lead',
        'left_pad', 'length', 'ln', 'log10', 'log2', 'lower', 'ltrim', 'make_col',
        'make_col_aggregated', 'make_object', 'make_resource', 'make_set_col', 'map_get',
        'map_keys', 'map_values', 'match', 'match_regex', 'max', 'md5', 'median', 'min',
        'mode', 'nanoseconds', 'nanoseconds_to_milliseconds', 'nanoseconds_to_seconds',
        'not_null', 'now', 'nth', 'null_if', 'num_bytes', 'num_codepoints', 'object_agg',
        'object_delete', 'parse_csv', 'parse_duration', 'parse_isotime', 'parse_json',
        'parse_key_value', 'parse_time', 'parse_timestamp', 'parse_url', 'parse_user_agent',
        'path', 'percentile', 'pi', 'pow', 'protocol', 'query_param', 'query_params',
        'radians_to_degrees', 'rand', 'regextract', 'regexmatch', 'replace', 'replace_regex',
        'right_pad', 'round', 'rtrim', 'search', 'sha1', 'sha256', 'sign', 'sin_deg',
        'sin_rad', 'sinh', 'slice', 'split', 'split_part', 'sqrt', 'starts_with', 'stddev',
        'string', 'string_agg', 'strip_null_columns', 'strip_prefix', 'strip_suffix',
        'strlen', 'strpos', 'substr', 'sum', 'tan_deg', 'tan_rad', 'tanh', 'tdigest_combine',
        'tdigest_merge', 'tdigest_quantile', 'time_bucket', 'timestamp', 'timestamp_ms',
        'timestamp_ns', 'timestamp_sec', 'timestamp_us', 'to_base64', 'to_hex', 'to_json',
        'to_lowercase', 'to_nanoseconds', 'to_proto_timestamp', 'to_uppercase', 'to_url',
        'tokenize', 'tokenize_pattern', 'top', 'trim', 'trunc', 'typeof', 'unnest',
        'unnest_cols', 'upper', 'url_encode', 'urlparse', 'variance', 'window',
        'm', 'm_tdigest', 'make_fields', 'value_counts', 'first_value', 'last_value',
        'nth_value', 'row_number', 'rank', 'dense_rank', 'percent_rank', 'cume_dist',
        'ntile', 'frame', 'group_by_all', 'get_field', 'set_field', 'delete_field',
        'at', 'every', 'extract_values', 'is_array', 'is_bool', 'is_int', 'is_float',
        'is_object', 'is_string', 'get_or_default', 'exists', 'not_exists', 'keys',
        'values', 'entries', 'merge_objects', 'parse_xml', 'case', 'when', 'otherwise',
        'split_to_array', 'array_join', 'slice_array', 'reverse_array', 'sort_array',
        'map', 'filter', 'reduce', 'zip', 'unzip', 'transpose', 'pivot', 'unpivot',
        'cross_join', 'lateral_view', 'explode', 'explode_outer', 'posexplode',
        'posexplode_outer', 'inline', 'inline_outer', 'stack', 'sequence', 'array_repeat',
        'array_position', 'array_remove', 'array_distinct', 'array_intersect',
        'array_union', 'array_except', 'shuffle', 'arrays_overlap', 'array_sort',
        'array_max', 'array_min', 'flatten', 'array_compact', 'element_at', 'cardinality',
        'size', 'sort_by', 'aggregate', 'transform', 'exists_any', 'forall', 'zip_with',
        'map_filter', 'map_zip_with', 'transform_keys', 'transform_values', 'map_from_arrays',
        'map_from_entries', 'map_concat', 'str_to_map', 'from_csv', 'schema_of_csv',
        'schema_of_json', 'to_csv', 'sentences', 'named_struct', 'bit_length',
        'char_length', 'character_length', 'ascii', 'base64', 'unbase64', 'decode',
        'encode', 'format_number', 'format_string', 'initcap', 'lcase', 'locate',
        'lpad', 'octet_length', 'overlay', 'position', 'printf', 'regexp_extract',
        'regexp_extract_all', 'regexp_replace', 'repeat', 'reverse', 'right', 'rpad',
        'soundex', 'space', 'split_string', 'substring', 'substring_index', 'translate',
        'ucase', 'unhex', 'xpath', 'xpath_boolean', 'xpath_double', 'xpath_float',
        'xpath_int', 'xpath_long', 'xpath_number', 'xpath_short', 'xpath_string'
    }

    # SQL→OPAL translation hints for common mistakes
    SQL_FUNCTION_HINTS = {
        'count_if': 'OPAL doesn\'t have count_if(). Use: make_col flag:if(condition,1,0) | statsby sum(flag)',
        'len': 'OPAL doesn\'t have len(). Use: strlen(string) or array_length(array)',
        'length': 'In OPAL, use: strlen(string) or array_length(array)',
        'isnull': 'OPAL doesn\'t have isnull(). Use: is_null(field)',
        'ifnull': 'OPAL doesn\'t have ifnull(). Use: coalesce(field, default_value)',
        'nvl': 'OPAL doesn\'t have nvl(). Use: coalesce(field, default_value)',
        'decode': 'OPAL doesn\'t have SQL-style decode(). Use: if() or case expressions',
        'to_char': 'OPAL doesn\'t have to_char(). Use: format_date() or string()',
        'to_date': 'OPAL doesn\'t have to_date(). Use: parse_time() or parse_timestamp()',
        'sysdate': 'OPAL doesn\'t have sysdate. Use: now()',
        'getdate': 'OPAL doesn\'t have getdate(). Use: now()'
    }

    # Complete list of OPAL verbs (69 verbs across 6 categories)
    ALLOWED_VERBS = {
        # Aggregate verbs
        'aggregate', 'align', 'dedup', 'distinct', 'fill', 'histogram',
        'make_event', 'rollup', 'statsby', 'timechart', 'top', 'top_logsources',
        'window', 'bottom',
        # Filter verbs
        'filter', 'filter_null', 'filter_repeated_source', 'filter_repeated_value',
        'flatten_leaves', 'flatten_single', 'limit', 'sample', 'search', 'tail',
        'union', 'where',
        # Join verbs
        'join', 'join_lookup', 'lookup', 'lookup_add', 'set_col_visible',
        'set_link', 'set_metric', 'top_grouping',
        # Metadata verbs
        'extract_regex', 'interface', 'make_col', 'make_resource', 'make_set_col',
        'pick', 'pick_col', 'remove_col', 'rename_col', 'set_col', 'set_col_enum',
        'set_col_tag', 'set_label', 'set_metadata', 'set_primary_key', 'set_severity',
        'set_type', 'set_valid_from', 'unwrap',
        # Projection verbs
        'colcount', 'columns', 'exists', 'fields', 'head', 'metadata', 'sample_distinct',
        'set_dataset_metadata',
        # Semistructured verbs
        'expand', 'flatten', 'make_fields', 'parse_csv', 'parse_kvs', 'parse_xml',
        'unflatten', 'unnest', 'make_object',
        # Sort verbs
        'sort'
    }

    # 1. Check for balanced parentheses, brackets, and braces
    if query.count('(') != query.count(')'):
        return ValidationResult(
            is_valid=False,
            transformed_query=query if all_transformations else None,
            transformations=all_transformations,
            error_message="Unbalanced parentheses in OPAL query"
        )
    if query.count('[') != query.count(']'):
        return ValidationResult(
            is_valid=False,
            transformed_query=query if all_transformations else None,
            transformations=all_transformations,
            error_message="Unbalanced brackets in OPAL query"
        )
    if query.count('{') != query.count('}'):
        return ValidationResult(
            is_valid=False,
            transformed_query=query if all_transformations else None,
            transformations=all_transformations,
            error_message="Unbalanced braces in OPAL query"
        )

    # 2. Check for balanced quotes (simplified - just count double quotes)
    # More sophisticated quote handling would require state machine
    double_quote_count = query.count('"')
    if double_quote_count % 2 != 0:
        return ValidationResult(
            is_valid=False,
            transformed_query=query if all_transformations else None,
            transformations=all_transformations,
            error_message="Unbalanced double quotes in OPAL query"
        )

    # 3. Check query complexity (prevent DoS)
    MAX_OPERATIONS = 20
    operations = [op.strip() for op in query.split('|') if op.strip()]
    if len(operations) > MAX_OPERATIONS:
        return ValidationResult(
            is_valid=False,
            transformed_query=query if all_transformations else None,
            transformations=all_transformations,
            error_message=f"Query too complex: {len(operations)} operations (max {MAX_OPERATIONS})"
        )

    # 4. Check nesting depth (prevent stack overflow)
    MAX_NESTING = 10
    max_depth = 0
    current_depth = 0
    for char in query:
        if char in '({[':
            current_depth += 1
            max_depth = max(max_depth, current_depth)
        elif char in ')}]':
            current_depth -= 1
    if max_depth > MAX_NESTING:
        return ValidationResult(
            is_valid=False,
            transformed_query=query if all_transformations else None,
            transformations=all_transformations,
            error_message=f"Query nesting too deep: {max_depth} levels (max {MAX_NESTING})"
        )

    # 5. Validate all verbs in the pipeline (not just the first one)
    for i, operation in enumerate(operations, 1):
        # Extract the first word (the verb)
        words = operation.strip().split()
        if not words:
            continue
        first_word = words[0]

        # Check if it's a valid OPAL verb
        if first_word not in ALLOWED_VERBS:
            similar_verbs = [v for v in ALLOWED_VERBS if v.startswith(first_word[:3])][:5]
            suggestion = f" Similar verbs: {', '.join(similar_verbs)}" if similar_verbs else ""
            return ValidationResult(
                is_valid=False,
                transformed_query=query if all_transformations else None,
                transformations=all_transformations,
                error_message=(
                    f"Unknown OPAL verb '{first_word}' at position {i} in pipeline. "
                    f"Valid verbs include: filter, make_col, statsby, timechart, sort, etc.{suggestion} "
                    f"(see https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALVerbs.html)"
                )
            )

    # 6. Validate function calls (including nested functions)
    # Use regex to find all function-like patterns: word followed by (
    function_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\('
    function_matches = re.findall(function_pattern, query)

    # Check each function against the whitelist
    for func_name in set(function_matches):
        if func_name not in ALLOWED_FUNCTIONS:
            # Check if it's a common SQL function with a hint
            if func_name in SQL_FUNCTION_HINTS:
                return ValidationResult(
                    is_valid=False,
                    transformed_query=query if all_transformations else None,
                    transformations=all_transformations,
                    error_message=f"Unknown function '{func_name}()'. {SQL_FUNCTION_HINTS[func_name]}"
                )
            else:
                # Provide helpful similar function suggestions
                similar_funcs = [f for f in ALLOWED_FUNCTIONS if f.startswith(func_name[:3])][:5]
                suggestion = f" Similar functions: {', '.join(similar_funcs)}" if similar_funcs else ""
                return ValidationResult(
                    is_valid=False,
                    transformed_query=query if all_transformations else None,
                    transformations=all_transformations,
                    error_message=(
                        f"Unknown function '{func_name}()'. "
                        f"Valid OPAL functions: count, sum, avg, if, contains, string, parse_json, etc.{suggestion} "
                        f"(see https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALFunctions.html)"
                    )
                )

    # 7. Check for common SQL-style sort syntax (sort -field instead of sort desc(field))
    # Check each operation in the pipeline (avoids matching inside quoted strings)
    for operation in operations:
        # Check if this operation starts with "sort -" (after stripping whitespace)
        stripped_op = operation.strip()
        if re.match(r'^sort\s+-', stripped_op):
            return ValidationResult(
                is_valid=False,
                transformed_query=query if all_transformations else None,
                transformations=all_transformations,
                error_message=(
                    "Invalid sort syntax. "
                    "OPAL uses 'sort desc(field)' not 'sort -field'. "
                    "Use: sort desc(field) for descending or sort asc(field) for ascending. "
                    "(see https://docs.observeinc.com/en/latest/content/query-language-reference/verbs/sort.html)"
                )
            )

    # NOTE: Multi-term angle bracket syntax is now AUTO-FIXED above (transform_multi_term_angle_brackets)
    # No longer blocking - we automatically convert to explicit OR logic

    # All validations passed
    return ValidationResult(
        is_valid=True,
        transformed_query=query if all_transformations else None,
        transformations=all_transformations,
        error_message=None
    )
