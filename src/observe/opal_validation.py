"""
OPAL Query Validation

Provides comprehensive validation for OPAL queries to catch errors early
and prevent common mistakes that lead to empty results or API errors.
"""

import re
from typing import Tuple, Optional


def validate_opal_query_structure(query: str) -> Tuple[bool, Optional[str]]:
    """
    Validate OPAL query structure for security and correctness.

    This performs structural validation without full semantic parsing:
    - Validates all verbs in piped sequences against whitelist
    - Checks balanced delimiters (prevents malformed queries)
    - Enforces complexity limits (prevents DoS)

    The Observe API remains the authoritative validator for full semantics.

    Args:
        query: OPAL query string to validate

    Returns:
        Tuple of (is_valid, error_message)

    Raises:
        ValueError: If query structure is invalid
    """
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
        return False, "Unbalanced parentheses in OPAL query"
    if query.count('[') != query.count(']'):
        return False, "Unbalanced brackets in OPAL query"
    if query.count('{') != query.count('}'):
        return False, "Unbalanced braces in OPAL query"

    # 2. Check for balanced quotes (simplified - just count double quotes)
    # More sophisticated quote handling would require state machine
    double_quote_count = query.count('"')
    if double_quote_count % 2 != 0:
        return False, "Unbalanced double quotes in OPAL query"

    # 3. Check query complexity (prevent DoS)
    MAX_OPERATIONS = 20
    operations = [op.strip() for op in query.split('|') if op.strip()]
    if len(operations) > MAX_OPERATIONS:
        return False, f"Query too complex: {len(operations)} operations (max {MAX_OPERATIONS})"

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
        return False, f"Query nesting too deep: {max_depth} levels (max {MAX_NESTING})"

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
            return False, (
                f"Unknown OPAL verb '{first_word}' at position {i} in pipeline. "
                f"Valid verbs include: filter, make_col, statsby, timechart, sort, etc.{suggestion} "
                f"(see https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALVerbs.html)"
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
                return False, f"Unknown function '{func_name}()'. {SQL_FUNCTION_HINTS[func_name]}"
            else:
                # Provide helpful similar function suggestions
                similar_funcs = [f for f in ALLOWED_FUNCTIONS if f.startswith(func_name[:3])][:5]
                suggestion = f" Similar functions: {', '.join(similar_funcs)}" if similar_funcs else ""
                return False, (
                    f"Unknown function '{func_name}()'. "
                    f"Valid OPAL functions: count, sum, avg, if, contains, string, parse_json, etc.{suggestion} "
                    f"(see https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALFunctions.html)"
                )

    # 7. Check for common SQL-style sort syntax (sort -field instead of sort desc(field))
    # Check each operation in the pipeline (avoids matching inside quoted strings)
    for operation in operations:
        # Check if this operation starts with "sort -" (after stripping whitespace)
        stripped_op = operation.strip()
        if re.match(r'^sort\s+-', stripped_op):
            return False, (
                "Invalid sort syntax. "
                "OPAL uses 'sort desc(field)' not 'sort -field'. "
                "Use: sort desc(field) for descending or sort asc(field) for ascending. "
                "(see https://docs.observeinc.com/en/latest/content/query-language-reference/verbs/sort.html)"
            )

    # 8. Check for multi-term angle bracket syntax <term1 term2 ...> which uses AND logic
    # LLMs often assume this is OR logic, leading to empty results
    multi_term_pattern = re.compile(r'<\s*(\S+(?:\s+\S+)+)\s*>')
    multi_term_matches = multi_term_pattern.findall(query)

    if multi_term_matches:
        example_terms = multi_term_matches[0].split()[:2]  # Get first two terms as example
        return False, (
            f"⚠️ Multi-term angle bracket syntax detected: <{' '.join(example_terms)} ...>\n"
            f"\n"
            f"This probably doesn't do what you wanted:\n"
            f"• In OPAL, <term1 term2> means 'term1 AND term2' (both must be present)\n"
            f"• Most LLMs assume this means 'term1 OR term2' (either present)\n"
            f"• This often results in empty query results\n"
            f"\n"
            f"Since we can't validate your intent, we're blocking this query.\n"
            f"\n"
            f"To fix, rewrite using explicit boolean logic:\n"
            f"\n"
            f"❌ Instead of: filter body ~ <{' '.join(example_terms)}>\n"
            f"✅ For OR:     filter contains(body, \"{example_terms[0]}\") or contains(body, \"{example_terms[1]}\")\n"
            f"✅ For AND:    filter contains(body, \"{example_terms[0]}\") and contains(body, \"{example_terms[1]}\")\n"
            f"✅ Single term: filter body ~ {example_terms[0]}\n"
            f"\n"
            f"Single-term angle brackets are fine: filter body ~ <error> works correctly."
        )

    return True, None
