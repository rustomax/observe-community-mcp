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
        'OBSERVATION_TIME',
        'start_time',      # OpenTelemetry span start time
        'end_time'         # OpenTelemetry span end time
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


def transform_nested_field_quoting(query: str) -> Tuple[str, List[str]]:
    """
    Auto-quote nested field names that contain dots.

    LLMs often write: resource_attributes.k8s.namespace.name
    Which OPAL interprets as: resource_attributes → k8s → namespace → name (4 levels)
    But actually means: resource_attributes → "k8s.namespace.name" (2 levels)

    This is the #1 cause of "field not found" errors in OpenTelemetry data.

    Examples:
        Input:  resource_attributes.k8s.namespace.name
        Output: resource_attributes."k8s.namespace.name"

        Input:  attributes.http.status_code
        Output: attributes."http.status_code"

        Input:  resource_attributes.service.name
        Output: resource_attributes.service.name (no change - valid field)

    Detection strategy:
    - Look for common parent fields (resource_attributes, attributes, fields)
    - Followed by known dotted prefixes (k8s., http., service., net., etc.)
    - Group and quote the dotted portion

    Returns:
        Tuple of (transformed_query, list_of_transformation_descriptions)
    """
    transformations = []

    # Common parent field names in OpenTelemetry
    PARENT_FIELDS = [
        'resource_attributes',
        'attributes',
        'fields',
        'span_attributes',
        'resource',
    ]

    # Known OpenTelemetry attribute prefixes that use dots
    # See: https://opentelemetry.io/docs/specs/semconv/
    DOTTED_PREFIXES = [
        'k8s',           # k8s.namespace.name, k8s.pod.name, etc.
        'http',          # http.status_code, http.method, etc.
        'service',       # service.instance.id, service.namespace, etc.
        'net',           # net.host.name, net.peer.name, etc.
        'db',            # db.system, db.connection_string, etc.
        'messaging',     # messaging.system, messaging.destination, etc.
        'rpc',           # rpc.system, rpc.service, etc.
        'code',          # code.function, code.namespace, etc.
        'enduser',       # enduser.id, enduser.role, etc.
        'thread',        # thread.id, thread.name, etc.
        'faas',          # faas.execution, faas.document, etc.
        'peer',          # peer.service, etc.
        'host',          # host.name, host.type, etc.
        'container',     # container.id, container.name, etc.
        'deployment',    # deployment.environment, etc.
        'telemetry',     # telemetry.sdk.name, etc.
        'cloud',         # cloud.provider, cloud.region, etc.
        'aws',           # aws.ecs.task.arn, etc.
        'gcp',           # gcp.gce.instance.name, etc.
        'azure',         # azure.vm.scaleset.name, etc.
    ]

    # Pattern to match field access that might need quoting
    # Matches: parent_field.prefix.more.stuff
    # We'll use a callback to inspect and transform each match
    parent_pattern = '|'.join(PARENT_FIELDS)
    prefix_pattern = '|'.join(DOTTED_PREFIXES)

    # Match: (parent_field).(dotted_prefix).rest.of.path
    # Capture groups: (1) parent field, (2) the FULL dotted path from prefix onward
    # Use negative lookahead to avoid already-quoted fields: (?!")
    # IMPORTANT: Wrap prefix_pattern in (?:...) so the dot applies to all alternatives
    # Then capture the whole expression including the prefix
    pattern = rf'\b({parent_pattern})\.(?!")((?:{prefix_pattern})\.[a-zA-Z0-9_.]+)'

    def replace_func(match):
        parent = match.group(1)
        dotted_path = match.group(2)

        # Check if this is already quoted (should be caught by negative lookahead, but extra safety)
        full_match = match.group(0)
        match_start = match.start()
        if match_start > 0 and query[match_start - 1] == '"':
            return full_match  # Already quoted

        # Build the quoted version
        replacement = f'{parent}."{dotted_path}"'

        # Create educational feedback
        transformations.append(
            f"✓ Auto-fix applied: Nested field name auto-quoted\n"
            f"  Original: {full_match}\n"
            f"  Fixed:    {replacement}\n"
            f"  Reason: Field names containing dots must be quoted in OPAL.\n"
            f"          Without quotes, '{dotted_path}' is interpreted as nested object access.\n"
            f"  Note: OpenTelemetry attributes like 'k8s.namespace.name' are single field names,\n"
            f"        not nested paths. Always quote them: \"{dotted_path}\""
        )

        return replacement

    transformed_query = re.sub(pattern, replace_func, query)

    # Check if any transformations were made
    if transformed_query != query:
        return transformed_query, transformations
    else:
        return query, []


def transform_sort_syntax(query: str) -> Tuple[str, List[str]]:
    """
    Auto-fix SQL-style sort syntax: sort -field → sort desc(field)

    LLMs often write: sort -field_name
    Which is SQL/shell syntax, not OPAL.

    OPAL requires: sort desc(field_name) or sort asc(field_name)

    Examples:
        Input:  sort -count
        Output: sort desc(count)

        Input:  filter error ~ true | sort -timestamp | limit 10
        Output: filter error ~ true | sort desc(timestamp) | limit 10

    Returns:
        Tuple of (transformed_query, list_of_transformation_descriptions)
    """
    transformations = []

    # Pattern to match: sort -field_name
    # Captures the field name after the minus sign
    # Field name can be simple (word) or complex (dotted path, quoted field)
    pattern = r'\bsort\s+-(\w+(?:\.\w+)*)'

    def replace_func(match):
        field_name = match.group(1)
        original = match.group(0)
        replacement = f'sort desc({field_name})'

        transformations.append(
            f"✓ Auto-fix applied: Sort syntax corrected\n"
            f"  Original: {original}\n"
            f"  Fixed:    {replacement}\n"
            f"  Reason: OPAL doesn't support SQL/shell-style 'sort -field' syntax.\n"
            f"          Use 'sort desc(field)' for descending or 'sort asc(field)' for ascending.\n"
            f"  Note: The minus prefix (-) has no meaning in OPAL sort operations."
        )

        return replacement

    transformed_query = re.sub(pattern, replace_func, query)

    if transformed_query != query:
        return transformed_query, transformations
    else:
        return query, []


def transform_count_if(query: str) -> Tuple[str, List[str]]:
    """
    Auto-fix count_if() function calls with proper OPAL pattern.

    LLMs often write: statsby count_if(condition)
    Which doesn't exist in OPAL.

    Proper OPAL pattern: make_col flag:if(condition,1,0) | statsby sum(flag)

    Examples:
        Input:  statsby error_count:count_if(severity="error")
        Output: make_col __count_if_error_count:if(severity="error",1,0) | statsby error_count:sum(__count_if_error_count)

        Input:  statsby errors:count_if(status_code >= 500), total:count()
        Output: make_col __count_if_errors:if(status_code >= 500,1,0) | statsby errors:sum(__count_if_errors), total:count()

    Returns:
        Tuple of (transformed_query, list_of_transformation_descriptions)
    """
    transformations = []

    # Pattern to match: label:count_if(condition)
    # Captures: (1) optional label before colon, (2) the condition inside count_if()
    # We need to handle this inside statsby or aggregate contexts
    pattern = r'\b(\w+):count_if\(([^)]+)\)'

    matches = list(re.finditer(pattern, query))

    if not matches:
        return query, []

    # Check if we're in a statsby or aggregate context
    # We need to inject a make_col before the statsby/aggregate
    transformed_query = query

    # Process each count_if occurrence
    for match in reversed(matches):  # Reverse to preserve positions
        label = match.group(1)
        condition = match.group(2)
        original_expr = match.group(0)

        # Generate a unique temp field name
        temp_field = f'__count_if_{label}'

        # Replace count_if(condition) with sum(temp_field)
        replacement_agg = f'{label}:sum({temp_field})'
        transformed_query = transformed_query.replace(original_expr, replacement_agg, 1)

        # Now we need to inject make_col BEFORE the statsby/aggregate
        # Find the statsby or aggregate that contains this expression
        # Look for "statsby" or "aggregate" before our match position

        # Split query into pipeline stages
        stages = [s.strip() for s in transformed_query.split('|')]

        # Find which stage contains our aggregation
        agg_stage_idx = None
        for idx, stage in enumerate(stages):
            if replacement_agg in stage and (stage.startswith('statsby') or stage.startswith('aggregate')):
                agg_stage_idx = idx
                break

        if agg_stage_idx is not None:
            # Insert make_col stage before the aggregation
            make_col_stage = f'make_col {temp_field}:if({condition},1,0)'

            # Check if there's already a make_col in this position
            if agg_stage_idx > 0 and stages[agg_stage_idx - 1].startswith('make_col'):
                # Append to existing make_col
                stages[agg_stage_idx - 1] += f', {temp_field}:if({condition},1,0)'
            else:
                # Insert new make_col stage
                stages.insert(agg_stage_idx, make_col_stage)

            transformed_query = ' | '.join(stages)

            transformations.append(
                f"✓ Auto-fix applied: count_if() converted to OPAL pattern\n"
                f"  Original: {original_expr}\n"
                f"  Fixed:    Added 'make_col {temp_field}:if({condition},1,0)' + '{replacement_agg}'\n"
                f"  Reason: OPAL doesn't have count_if() function.\n"
                f"          Use make_col with if() to create a flag, then sum() in aggregation.\n"
                f"  Note: Pattern is: make_col flag:if(condition,1,0) | statsby sum(flag)"
            )

    if transformed_query != query:
        return transformed_query, transformations
    else:
        return query, []


def transform_metric_pipeline(query: str) -> Tuple[str, List[str]]:
    """
    Auto-fix metric queries missing required align verb.

    LLMs often write: filter m("metric_name") > 0
    Or: statsby sum(m("metric_name"))

    But metrics REQUIRE: align + m() + aggregate pattern

    Examples:
        Input:  filter m("k8s_pod_cpu_usage") > 1000000
        Output: align 5m, cpu:avg(m("k8s_pod_cpu_usage")) | filter cpu > 1000000

        Input:  statsby errors:sum(m("error_count")), group_by(service_name)
        Output: align 5m, errors:sum(m("error_count")) | statsby errors:sum(errors), group_by(service_name)

    Returns:
        Tuple of (transformed_query, list_of_transformation_descriptions)
    """
    transformations = []

    # First, check if query contains m() or m_tdigest() calls
    has_metric_function = bool(re.search(r'\bm(?:_tdigest)?\s*\(', query))

    if not has_metric_function:
        return query, []

    # Check if query already has align verb
    has_align = bool(re.search(r'\balign\s+', query))

    if has_align:
        # Already has align, no transformation needed
        return query, []

    # Query has m() but no align - need to inject align

    # Pattern 1: filter m("metric") OPERATOR value
    # Example: filter m("metric_name") > 0
    filter_pattern = r'\bfilter\s+m(?:_tdigest)?\s*\([^)]+\)\s*([><=!]+)\s*([^\s|]+)'
    filter_match = re.search(filter_pattern, query)

    if filter_match:
        # Extract the full m() call
        m_call_pattern = r'm(?:_tdigest)?\s*\([^)]+\)'
        m_call = re.search(m_call_pattern, query).group(0)
        operator = filter_match.group(1)
        threshold = filter_match.group(2)

        # Determine aggregation function - default to avg for filter context
        agg_func = 'avg'
        if operator in ['>', '>=']:
            agg_func = 'max'  # If filtering for high values, use max
        elif operator in ['<', '<=']:
            agg_func = 'min'  # If filtering for low values, use min

        # Build the align stage
        temp_field = 'metric_value'
        align_stage = f'align 5m, {temp_field}:{agg_func}({m_call})'

        # Replace the filter with field reference
        new_filter = f'filter {temp_field} {operator} {threshold}'
        original_filter = filter_match.group(0)

        # Build transformed query
        rest_of_query = query.replace(original_filter, new_filter, 1)
        transformed_query = f'{align_stage} | {rest_of_query}'

        transformations.append(
            f"✓ Auto-fix applied: Metric query missing align verb\n"
            f"  Original: {original_filter}\n"
            f"  Fixed:    {align_stage} | {new_filter}\n"
            f"  Reason: Metrics require the align+m()+aggregate pattern.\n"
            f"          The m() function only works inside align verb.\n"
            f"  Note: align [interval], field:aggregation(m(\"metric_name\"))\n"
            f"        Common intervals: 1m, 5m, 15m, 1h"
        )

        return transformed_query, transformations

    # Pattern 2: statsby/aggregate with m() calls
    # Example: statsby errors:sum(m("error_count"))
    agg_pattern = r'\b(statsby|aggregate)\s+.*?m(?:_tdigest)?\s*\([^)]+\)'
    agg_match = re.search(agg_pattern, query)

    if agg_match:
        # Find all metric aggregations like label:agg_func(m("metric"))
        metric_agg_pattern = r'(\w+):(sum|avg|min|max|count|tdigest_combine)\s*\(\s*m(?:_tdigest)?\s*\(([^)]+)\)\s*\)'
        metric_aggs = list(re.finditer(metric_agg_pattern, query))

        if not metric_aggs:
            return query, []

        # Build align stage with all metric aggregations
        align_parts = []
        replacements = []

        for match in metric_aggs:
            label = match.group(1)
            agg_func = match.group(2)
            metric_name = match.group(3)

            # Create align aggregation
            if agg_func == 'tdigest_combine':
                # Special handling for tdigest
                align_parts.append(f'{label}:tdigest_combine(m_tdigest({metric_name}))')
            else:
                align_parts.append(f'{label}:{agg_func}(m({metric_name}))')

            # Track replacement: m("metric") -> field_name
            original = match.group(0)
            # In statsby, keep the same label but reference the aligned field
            replacement = f'{label}:{agg_func}({label})'
            replacements.append((original, replacement))

        # Build align stage
        align_stage = 'align 5m, ' + ', '.join(align_parts)

        # Replace m() calls in the rest of the query
        transformed_query = query
        for original, replacement in replacements:
            transformed_query = transformed_query.replace(original, replacement, 1)

        # Prepend align stage
        transformed_query = f'{align_stage} | {transformed_query}'

        transformations.append(
            f"✓ Auto-fix applied: Metric aggregation missing align verb\n"
            f"  Original: {agg_match.group(0)[:80]}...\n"
            f"  Fixed:    {align_stage} | ...\n"
            f"  Reason: Metric queries require align before aggregation.\n"
            f"          Pattern: align [interval], field:agg(m(\"metric\")) | aggregate/statsby\n"
            f"  Note: The align stage time-buckets metrics, then you aggregate across dimensions."
        )

        return transformed_query, transformations

    # If we have m() but didn't match known patterns, return unchanged
    # The query will likely fail validation, but we don't want to make incorrect assumptions
    return query, []


def _split_pipeline_safely(query: str) -> list[str]:
    """
    Split an OPAL query into pipeline operations, respecting regex delimiters.

    The pipe character '|' is used both as:
    1. Pipeline operator between OPAL verbs
    2. Regex OR operator inside regex patterns (e.g., /error|exception|fail/)

    This function correctly handles the latter case by tracking regex context.

    Args:
        query: The OPAL query string to split

    Returns:
        List of pipeline operations (strings)

    Example:
        >>> _split_pipeline_safely('filter body ~ /error|exception/i | make_col x:1')
        ['filter body ~ /error|exception/i', 'make_col x:1']
    """
    operations = []
    current_op = []
    in_regex = False
    in_double_quote = False
    in_single_quote = False
    escape_next = False

    i = 0
    while i < len(query):
        char = query[i]

        # Handle escape sequences
        if escape_next:
            current_op.append(char)
            escape_next = False
            i += 1
            continue

        if char == '\\':
            current_op.append(char)
            escape_next = True
            i += 1
            continue

        # Track string contexts (strings can contain / that aren't regex delimiters)
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current_op.append(char)
            i += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current_op.append(char)
            i += 1
            continue

        # Don't process special characters inside strings
        if in_double_quote or in_single_quote:
            current_op.append(char)
            i += 1
            continue

        # Track regex context
        # Regex patterns in OPAL are delimited by / ... / with optional flags like /i
        if char == '/':
            # Check if this is a regex delimiter (not division operator)
            # Heuristic: preceded by whitespace or operators like ~, =, !=
            if i > 0:
                prev_chars = query[max(0, i-3):i].strip()
                # Common patterns before regex: "~ /", "= /", "!= /", or start of line
                if prev_chars.endswith('~') or prev_chars.endswith('=') or prev_chars.endswith('!=') or i == 0:
                    in_regex = not in_regex
                # If we're already in a regex, this closes it (with possible flags after)
                elif in_regex:
                    in_regex = False
                    current_op.append(char)
                    # Consume any regex flags (i, g, m, etc.)
                    i += 1
                    while i < len(query) and query[i] in 'igmsuy':
                        current_op.append(query[i])
                        i += 1
                    continue
            else:
                # At start of query, assume it's a regex delimiter
                in_regex = not in_regex

            current_op.append(char)
            i += 1
            continue

        # Handle pipe character
        if char == '|':
            if in_regex:
                # Inside regex, | is the OR operator, not a pipeline separator
                current_op.append(char)
            else:
                # Outside regex, | separates pipeline operations
                op_str = ''.join(current_op).strip()
                if op_str:
                    operations.append(op_str)
                current_op = []
            i += 1
            continue

        # Regular character
        current_op.append(char)
        i += 1

    # Add the final operation
    op_str = ''.join(current_op).strip()
    if op_str:
        operations.append(op_str)

    return operations


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
    - Nested field quoting: resource_attributes.k8s.namespace.name → resource_attributes."k8s.namespace.name"
    - Sort syntax: sort -field → sort desc(field)
    - count_if() function: label:count_if(cond) → make_col flag:if(cond,1,0) | statsby label:sum(flag)
    - Metric pipeline: m() outside align → align + m() + aggregate pattern

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
    # Transform 1: Metric pipeline detection (structural - do this first, before field quoting)
    # This must come first because it restructures the entire query
    query, metric_pipeline_transforms = transform_metric_pipeline(query)
    all_transformations.extend(metric_pipeline_transforms)

    # Transform 2: Nested field quoting (structural fix)
    query, field_quoting_transforms = transform_nested_field_quoting(query)
    all_transformations.extend(field_quoting_transforms)

    # Transform 3: Multi-term angle brackets
    query, angle_bracket_transforms = transform_multi_term_angle_brackets(query)
    all_transformations.extend(angle_bracket_transforms)

    # Transform 4: Redundant time filters (when time_range is set)
    query, time_filter_transforms = transform_redundant_time_filters(query, time_range)
    all_transformations.extend(time_filter_transforms)

    # Transform 5: Sort syntax (SQL-style to OPAL)
    query, sort_transforms = transform_sort_syntax(query)
    all_transformations.extend(sort_transforms)

    # Transform 6: count_if() function (doesn't exist in OPAL)
    query, count_if_transforms = transform_count_if(query)
    all_transformations.extend(count_if_transforms)

    # Complete list of OPAL functions (476 functions across 11 categories)
    ALLOWED_FUNCTIONS = {
        'abs', 'any', 'any_not_null', 'append_item', 'arccos_deg', 'arccos_rad',
        'asc', 'desc',  # Sort direction functions
        'arcsin_deg', 'arcsin_rad', 'arctan2_deg', 'arctan2_rad', 'arctan_deg',
        'arctan_rad', 'array', 'array_agg', 'array_agg_distinct', 'array_concat',
        'array_contains', 'array_flatten', 'array_length', 'array_null', 'array_to_string',
        'array_union_agg', 'atoi', 'avg', 'base64decode', 'base64encode', 'bin_end_time',
        'bin_size', 'bin_start_time', 'bool', 'bool_null', 'cast',
        'cbrt', 'ceil', 'check_json', 'coalesce', 'concat', 'concat_arrays', 'concat_strings',
        'contains', 'cos_deg', 'cos_rad', 'cosh', 'count', 'count_distinct', 'count_distinct_exact',
        'count_regex_matches', 'decode_base64', 'decode_uri', 'decode_uri_component', 'degrees',
        'delta', 'delta_monotonic', 'dense_rank', 'deriv', 'desc', 'detect_browser', 'distinct_count',
        'drop_fields', 'duration', 'duration_hr', 'duration_min', 'duration_ms', 'duration_ns',
        'duration_null', 'duration_sec', 'duration_us', 'editdistance', 'embed_sql_params',
        'encode_base64', 'encode_uri', 'encode_uri_component', 'ends_with', 'eq', 'ewma',
        'exp', 'exponential_histogram_null', 'extract_all', 'filter_index',
        'find_index', 'first', 'first_not_null', 'firstnotnull', 'float64', 'float64_null', 'floor',
        'fold_any', 'fold_interval', 'format_date', 'format_duration', 'format_time', 'format_url',
        'frac', 'frame', 'frame_exact', 'frame_following', 'frame_preceding', 'from_base64',
        'from_epochms', 'from_epochns', 'from_hex', 'from_json', 'from_milliseconds',
        'from_nanoseconds', 'from_proto_timestamp', 'from_seconds', 'from_url', 'get_field',
        'get_item', 'get_jmespath', 'get_regex', 'get_regex_all', 'group_by', 'gt', 'gte',
        'hash', 'hash_agg', 'hash_agg_distinct', 'haversine_distance_km', 'histogram_combine',
        'histogram_fraction', 'histogram_null', 'histogram_quantile', 'host', 'if', 'if_null',
        'in', 'index_of_item', 'insert_item', 'int', 'int64', 'int64_null', 'int64_to_ipv4',
        'int_div', 'intersect_arrays',
        'ipaddr', 'ipsubnet', 'ipv4', 'ipv4_address_in_network', 'ipv4_network_int64',
        'ipv4_to_int64', 'is_ipv4', 'is_ipv6', 'is_null', 'is_private_ip', 'is_url',
        'json_extract', 'json_group_object', 'label', 'lag', 'lag_not_null', 'last',
        'last_not_null', 'lastnotnull', 'lead', 'lead_not_null', 'left', 'left_pad',
        'length', 'like', 'ln', 'log', 'log10', 'log2', 'lower', 'lt', 'lte', 'ltrim',
        'm', 'm_exponential_histogram', 'm_histogram', 'm_object', 'm_tdigest', 'make_array',
        'make_array_range', 'make_col', 'make_col_aggregated', 'make_fields', 'make_object',
        'make_resource', 'make_set_col', 'map_get',
        'map_keys', 'map_values', 'match', 'match_regex', 'max', 'md5', 'median', 'median_exact',
        'merge_objects', 'metric', 'min', 'mod', 'mode', 'nanoseconds',
        'nanoseconds_to_milliseconds', 'nanoseconds_to_seconds', 'ne', 'not_null', 'now',
        'nth', 'null_if', 'nullsfirst', 'nullslast', 'num_bytes', 'num_codepoints',
        'numeric_null', 'object', 'object_agg', 'object_keys', 'object_null', 'on', 'order_by',
        'otel_exponential_histogram_quantile', 'otel_exponential_histogram_sum',
        'otel_histogram_quantile', 'otel_histogram_sum',
        'object_delete', 'options', 'parse_csv', 'parse_duration', 'parse_hex', 'parse_ip',
        'parse_isotime', 'parse_json', 'parse_key_value', 'parse_kvs', 'parse_time',
        'parse_timestamp', 'parse_url', 'parse_user_agent', 'path', 'path_exists',
        'percentile', 'percentile_cont', 'percentile_disc', 'pi', 'pick_fields',
        'pivot_array', 'position', 'pow', 'prepend_item', 'primary_key', 'prom_quantile',
        'protocol', 'query_end_time', 'query_param', 'query_params', 'query_start_time',
        'radians', 'radians_to_degrees', 'rand', 'rank', 'rate', 'regex', 'regextract',
        'regexmatch', 'replace', 'replace_regex',
        'right', 'right_pad', 'round', 'row_end_time', 'row_number', 'row_timestamp', 'rpad',
        'rtrim', 'same', 'search', 'sha1', 'sha2', 'sha256', 'sign', 'sin_deg', 'sin_rad',
        'sinh', 'slice', 'slice_array', 'sort_array', 'split', 'split_part', 'sqrt',
        'starts_with', 'stddev', 'string', 'string_agg', 'string_agg_distinct', 'string_null',
        'strip_null_columns', 'strip_prefix', 'strip_suffix', 'strlen', 'strpos', 'substr',
        'sum', 'tags', 'tan_deg', 'tan_rad', 'tanh', 'tdigest', 'tdigest_agg', 'tdigest_combine',
        'tdigest_merge', 'tdigest_null', 'tdigest_quantile', 'time_bucket', 'timestamp',
        'timestamp_ms', 'timestamp_ns', 'timestamp_null', 'timestamp_sec', 'timestamp_us',
        'to_base64', 'to_days', 'to_hex', 'to_hours', 'to_json', 'to_lowercase',
        'to_milliseconds', 'to_minutes', 'to_nanoseconds', 'to_proto_timestamp',
        'to_seconds', 'to_uppercase', 'to_url', 'to_weeks', 'tokenize', 'tokenize_part',
        'tokenize_pattern', 'top', 'topk_agg', 'trim', 'trunc', 'typeof', 'uniform',
        'unnest',
        'unnest_cols', 'unpivot_array', 'upper', 'url_encode', 'urlparse', 'valid_for',
        'value_counts', 'variant_null', 'variant_type_name', 'variance', 'width_bucket',
        'window', 'zipf',
        # Additional window/analytic functions (already listed above in different context)
        'first_value', 'last_value', 'nth_value', 'percent_rank', 'cume_dist',
        'ntile', 'group_by_all', 'get_field', 'set_field', 'delete_field',
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

    # Complete list of OPAL verbs (108 verbs across 6 categories)
    ALLOWED_VERBS = {
        # Aggregate verbs
        'aggregate', 'align', 'always', 'bottomk', 'dedup', 'distinct', 'ever', 'fill',
        'histogram', 'make_event', 'merge_events', 'never', 'rollup', 'statsby',
        'timechart', 'timeshift', 'timestats', 'top', 'topk', 'top_logsources', 'window', 'bottom',
        # Filter verbs
        'filter', 'filter_last', 'filter_null', 'filter_repeated_source', 'filter_repeated_value',
        'flatten_all', 'flatten_leaves', 'flatten_single', 'limit', 'sample', 'search', 'tail',
        'union', 'unsort', 'where',
        # Join verbs
        'join', 'join_lookup', 'lookup', 'lookup_add', 'lookup_ip_info', 'set_col_visible',
        'set_link', 'set_metric', 'top_grouping', 'follow', 'leftjoin', 'fulljoin',
        'follow_not', 'not_exists', 'surrounding', 'update_resource',
        # Metadata verbs
        'add_key', 'drop_col', 'drop_interface', 'extract_regex', 'interface', 'make_col',
        'make_interval', 'make_metric', 'make_reference', 'make_resource', 'make_session',
        'make_set_col', 'make_table', 'pick', 'pick_col', 'remove_col', 'rename_col',
        'set_col', 'set_col_enum', 'set_col_immutable', 'set_col_searchable', 'set_col_tag',
        'set_label', 'set_metadata', 'set_metric_metadata', 'set_primary_key', 'set_severity',
        'set_timestamp', 'set_type', 'set_valid_from', 'set_valid_to', 'unset_all_links',
        'unset_keys', 'unset_link', 'unwrap',
        # Projection verbs
        'colcount', 'columns', 'exists', 'fields', 'head', 'metadata', 'sample_distinct',
        'set_dataset_metadata',
        # Semistructured verbs
        'expand', 'flatten', 'make_fields', 'parse_csv', 'parse_kvs', 'parse_xml',
        'pivot', 'unflatten', 'unnest', 'unpivot', 'make_object',
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
    operations = _split_pipeline_safely(query)
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
        # Use regex to extract just the verb name (alphanumeric + underscore)
        # This handles cases like "union(" where there's no space before the parenthesis
        verb_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)', operation.strip())
        if not verb_match:
            continue
        first_word = verb_match.group(1)

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
    # Skip verbs that happen to have parentheses (like union(...), pivot(...))
    for func_name in set(function_matches):
        # Skip if it's actually a verb, not a function
        if func_name in ALLOWED_VERBS:
            continue

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

    # NOTE: Common syntax issues are now AUTO-FIXED above:
    # - Multi-term angle bracket syntax → contains() OR logic (transform_multi_term_angle_brackets)
    # - SQL-style sort syntax → sort desc(field) (transform_sort_syntax)
    # - count_if() function → make_col + if() + sum() (transform_count_if)
    # No longer blocking - we automatically convert to correct OPAL syntax

    # All validations passed
    return ValidationResult(
        is_valid=True,
        transformed_query=query if all_transformations else None,
        transformations=all_transformations,
        error_message=None
    )
