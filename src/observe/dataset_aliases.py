"""
Dataset alias resolution for multi-dataset OPAL queries.

This module provides functionality to resolve dataset aliases and validate
dataset references in OPAL queries before execution.
"""

import re
import sys
from typing import Dict, List, Optional, Set, Tuple

def extract_dataset_references(query: str) -> List[str]:
    """
    Extract all dataset references from an OPAL query.
    
    Args:
        query: OPAL query string
        
    Returns:
        List of dataset references found in the query
        
    Examples:
        extract_dataset_references("join on(id=@volumes.id)")
        # Returns: ["@volumes"]
        
        extract_dataset_references("union @\"44508111\"")  
        # Returns: ["@\"44508111\""]
    """
    # Pattern to match dataset references:
    # @alias, @"quoted_name", @44508111 (numeric IDs)
    patterns = [
        r'@"[^"]+"',      # @"quoted dataset name"
        r'@\w+',          # @alias_name  
        r'@\d+',          # @44508111
    ]
    
    references = []
    for pattern in patterns:
        matches = re.findall(pattern, query)
        references.extend(matches)
    
    return list(set(references))  # Remove duplicates


def resolve_dataset_aliases(
    query: str,
    dataset_aliases: Optional[Dict[str, str]] = None,
    available_datasets: Optional[List[Dict[str, str]]] = None
) -> Tuple[str, Dict[str, str], List[str]]:
    """
    Resolve dataset aliases in an OPAL query to actual dataset IDs.
    
    Args:
        query: OPAL query containing dataset references
        dataset_aliases: Mapping of aliases to dataset IDs
        available_datasets: List of available datasets with id and name
        
    Returns:
        Tuple of (resolved_query, final_aliases, warnings)
        
    Examples:
        query = "join on(instanceId=@volumes.instanceId)"
        aliases = {"volumes": "44508111"}
        resolve_dataset_aliases(query, aliases)
        # Returns: (original_query, {"volumes": "44508111"}, [])
    """
    if not dataset_aliases:
        dataset_aliases = {}
    
    if not available_datasets:
        available_datasets = []
    
    resolved_aliases = dataset_aliases.copy()
    warnings = []
    resolved_query = query
    
    # Extract all dataset references from the query
    references = extract_dataset_references(query)
    
    if not references:
        return resolved_query, resolved_aliases, warnings
    
    print(f"[ALIAS_RESOLUTION] Found dataset references: {references}", file=sys.stderr)
    
    for ref in references:
        # Clean the reference (remove @ symbol)
        clean_ref = ref[1:]  # Remove @
        
        if clean_ref.startswith('"') and clean_ref.endswith('"'):
            # Quoted dataset name - try to resolve by name
            dataset_name = clean_ref[1:-1]  # Remove quotes
            
            # Look for dataset by name
            matching_dataset = None
            for dataset in available_datasets:
                if dataset.get('name', '').lower() == dataset_name.lower():
                    matching_dataset = dataset
                    break
            
            if matching_dataset:
                alias = dataset_name.replace(' ', '_').lower()
                resolved_aliases[alias] = matching_dataset['id']
                print(f"[ALIAS_RESOLUTION] Resolved quoted name '{dataset_name}' -> {matching_dataset['id']} (alias: {alias})", file=sys.stderr)
            else:
                warnings.append(f"Dataset name '{dataset_name}' not found in available datasets")
                
        elif clean_ref.isdigit():
            # Numeric dataset ID - validate it exists
            dataset_id = clean_ref
            
            # Check if this ID exists in available datasets
            id_exists = any(d.get('id') == dataset_id for d in available_datasets)
            
            if id_exists:
                # Use the numeric ID as both alias and ID
                resolved_aliases[f"dataset_{dataset_id}"] = dataset_id
                print(f"[ALIAS_RESOLUTION] Validated numeric ID {dataset_id}", file=sys.stderr)
            else:
                warnings.append(f"Dataset ID '{dataset_id}' not found in available datasets")
                
        else:
            # Simple alias - check if it's already resolved
            if clean_ref not in resolved_aliases:
                # Try to find a matching dataset by partial name match
                matching_datasets = []
                for dataset in available_datasets:
                    dataset_name = dataset.get('name', '').lower()
                    if clean_ref.lower() in dataset_name or dataset_name.endswith(clean_ref.lower()):
                        matching_datasets.append(dataset)
                
                if len(matching_datasets) == 1:
                    # Single match found
                    resolved_aliases[clean_ref] = matching_datasets[0]['id']
                    print(f"[ALIAS_RESOLUTION] Auto-resolved alias '{clean_ref}' -> {matching_datasets[0]['id']} ({matching_datasets[0]['name']})", file=sys.stderr)
                elif len(matching_datasets) > 1:
                    # Multiple matches - use the first one but warn
                    resolved_aliases[clean_ref] = matching_datasets[0]['id']
                    dataset_names = [d['name'] for d in matching_datasets]
                    warnings.append(f"Multiple datasets match alias '{clean_ref}': {dataset_names}. Using {matching_datasets[0]['name']}")
                    print(f"[ALIAS_RESOLUTION] Multiple matches for '{clean_ref}', using {matching_datasets[0]['name']}", file=sys.stderr)
                else:
                    warnings.append(f"Alias '{clean_ref}' could not be resolved to any available dataset")
    
    return resolved_query, resolved_aliases, warnings


def validate_multi_dataset_query(
    query: str,
    primary_dataset_id: str,
    secondary_dataset_ids: Optional[List[str]] = None,
    dataset_aliases: Optional[Dict[str, str]] = None
) -> Tuple[bool, List[str]]:
    """
    Validate that a multi-dataset OPAL query has all necessary datasets available.
    
    Args:
        query: OPAL query string
        primary_dataset_id: ID of the primary dataset
        secondary_dataset_ids: List of secondary dataset IDs
        dataset_aliases: Mapping of aliases to dataset IDs
        
    Returns:
        Tuple of (is_valid, validation_errors)
    """
    if not secondary_dataset_ids:
        secondary_dataset_ids = []
    
    if not dataset_aliases:
        dataset_aliases = {}
    
    errors = []
    
    # Extract dataset references from query
    references = extract_dataset_references(query)
    
    if not references:
        # No dataset references found - this is a single dataset query
        return True, []
    
    print(f"[QUERY_VALIDATION] Validating multi-dataset query with references: {references}", file=sys.stderr)
    print(f"[QUERY_VALIDATION] Available aliases: {list(dataset_aliases.keys())}", file=sys.stderr)
    print(f"[QUERY_VALIDATION] Secondary datasets: {secondary_dataset_ids}", file=sys.stderr)
    
    # Check that all references can be resolved
    all_dataset_ids = set([primary_dataset_id] + secondary_dataset_ids)
    
    for ref in references:
        clean_ref = ref[1:]  # Remove @ symbol
        
        if clean_ref.startswith('"') and clean_ref.endswith('"'):
            # Quoted name - should be resolved via aliases
            dataset_name = clean_ref[1:-1]
            alias = dataset_name.replace(' ', '_').lower()
            
            if alias not in dataset_aliases:
                errors.append(f"Quoted dataset reference '{ref}' has no corresponding alias mapping")
                continue
                
            if dataset_aliases[alias] not in all_dataset_ids:
                errors.append(f"Dataset reference '{ref}' resolves to {dataset_aliases[alias]} which is not in available datasets")
                
        elif clean_ref.isdigit():
            # Numeric ID
            if clean_ref not in all_dataset_ids:
                errors.append(f"Dataset reference '{ref}' (ID: {clean_ref}) is not in available datasets")
                
        else:
            # Simple alias
            if clean_ref not in dataset_aliases:
                errors.append(f"Dataset alias '{ref}' is not defined in dataset_aliases mapping")
                continue
                
            if dataset_aliases[clean_ref] not in all_dataset_ids:
                errors.append(f"Dataset alias '{ref}' resolves to {dataset_aliases[clean_ref]} which is not in available datasets")
    
    is_valid = len(errors) == 0
    
    if is_valid:
        print(f"[QUERY_VALIDATION] Multi-dataset query validation passed", file=sys.stderr)
    else:
        print(f"[QUERY_VALIDATION] Multi-dataset query validation failed: {errors}", file=sys.stderr)
    
    return is_valid, errors


def suggest_dataset_for_alias(
    alias: str,
    available_datasets: List[Dict[str, str]],
    similarity_threshold: float = 0.5
) -> Optional[Dict[str, str]]:
    """
    Suggest a dataset for an unresolved alias based on name similarity.
    
    Args:
        alias: The unresolved alias
        available_datasets: List of available datasets
        similarity_threshold: Minimum similarity score (0.0 to 1.0)
        
    Returns:
        Best matching dataset dict or None
    """
    if not available_datasets:
        return None
    
    alias_lower = alias.lower()
    
    # Simple similarity scoring based on substring matching
    best_match = None
    best_score = 0.0
    
    for dataset in available_datasets:
        dataset_name = dataset.get('name', '').lower()
        
        # Calculate simple similarity score
        score = 0.0
        
        # Exact substring match gets high score
        if alias_lower in dataset_name:
            score = 0.8 + (len(alias_lower) / len(dataset_name)) * 0.2
        elif dataset_name.endswith(alias_lower):
            score = 0.7
        elif any(word in dataset_name for word in alias_lower.split('_')):
            score = 0.6
        
        # Common alias patterns
        if alias_lower == 'volumes' and 'volume' in dataset_name:
            score = max(score, 0.9)
        elif alias_lower == 'instances' and 'instance' in dataset_name:
            score = max(score, 0.9)
        elif alias_lower == 'pods' and 'pod' in dataset_name:
            score = max(score, 0.9)
        elif alias_lower == 'containers' and 'container' in dataset_name:
            score = max(score, 0.9)
        elif alias_lower == 'events' and ('event' in dataset_name or 'cloudtrail' in dataset_name):
            score = max(score, 0.8)
        
        if score > best_score and score >= similarity_threshold:
            best_score = score
            best_match = dataset
    
    if best_match:
        print(f"[ALIAS_SUGGESTION] Suggested dataset for alias '{alias}': {best_match['name']} (score: {best_score:.2f})", file=sys.stderr)
    
    return best_match


def build_dataset_context(
    primary_dataset_id: str,
    secondary_dataset_ids: Optional[List[str]] = None,
    dataset_aliases: Optional[Dict[str, str]] = None,
    available_datasets: Optional[List[Dict[str, str]]] = None
) -> Dict[str, any]:
    """
    Build a dataset context object for multi-dataset query execution.
    
    Args:
        primary_dataset_id: ID of the primary dataset
        secondary_dataset_ids: List of secondary dataset IDs
        dataset_aliases: Mapping of aliases to dataset IDs
        available_datasets: List of available datasets for name resolution
        
    Returns:
        Dataset context dict suitable for API calls
    """
    if not secondary_dataset_ids:
        secondary_dataset_ids = []
    
    if not dataset_aliases:
        dataset_aliases = {}
    
    if not available_datasets:
        available_datasets = []
    
    # Create a name lookup for datasets
    name_lookup = {d.get('id'): d.get('name', f'Dataset {d.get("id")}') 
                   for d in available_datasets}
    
    context = {
        "primary": {
            "id": primary_dataset_id,
            "alias": "main",
            "name": name_lookup.get(primary_dataset_id, f"Dataset {primary_dataset_id}")
        },
        "secondary": []
    }
    
    # Add secondary datasets
    for i, dataset_id in enumerate(secondary_dataset_ids):
        # Find alias for this dataset ID
        alias = None
        for alias_name, alias_id in dataset_aliases.items():
            if alias_id == dataset_id:
                alias = alias_name
                break
        
        if not alias:
            alias = f"dataset_{i+1}"
        
        context["secondary"].append({
            "id": dataset_id,
            "alias": alias,
            "name": name_lookup.get(dataset_id, f"Dataset {dataset_id}")
        })
    
    print(f"[DATASET_CONTEXT] Built context with {len(context['secondary'])} secondary datasets", file=sys.stderr)
    
    return context