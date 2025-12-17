#!/usr/bin/env python3
"""
Config Filter Module

Shared module for loading and applying YAML-based dataset filters
for the intelligence scripts (datasets_intelligence.py and metrics_intelligence.py).

Config file format (YAML):
    mode: allowlist  # or blocklist

    include:
      by_id:
        - "41234567"
        - "41234568"

    exclude:
      by_id:
        - "31321231"

Modes:
    - allowlist: Only process datasets in include.by_id (exclude is ignored)
    - blocklist: Process all datasets except those in exclude.by_id (include is ignored)

Note: Config filtering requires --force flag (clean database) to work properly.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Set

import yaml

logger = logging.getLogger(__name__)


class FilterMode(Enum):
    """Filter mode for dataset processing."""
    ALLOWLIST = "allowlist"
    BLOCKLIST = "blocklist"


class ConfigError(Exception):
    """Raised when config file is invalid."""
    pass


@dataclass
class DatasetFilter:
    """
    Dataset filter configuration.

    Attributes:
        mode: Filter mode (allowlist or blocklist)
        include_ids: Set of dataset IDs to include (used in allowlist mode)
        exclude_ids: Set of dataset IDs to exclude (used in blocklist mode)
    """
    mode: FilterMode
    include_ids: Set[str] = field(default_factory=set)
    exclude_ids: Set[str] = field(default_factory=set)

    def should_process(self, dataset_id: str) -> bool:
        """
        Determine if a dataset should be processed based on filter rules.

        Args:
            dataset_id: The numeric dataset ID (e.g., "41234567")

        Returns:
            True if dataset should be processed, False if it should be skipped
        """
        if self.mode == FilterMode.ALLOWLIST:
            # In allowlist mode, only process if in include list
            return dataset_id in self.include_ids
        else:
            # In blocklist mode, process unless in exclude list
            return dataset_id not in self.exclude_ids

    def get_summary(self) -> str:
        """
        Get a human-readable summary of the filter configuration.

        Returns:
            Summary string suitable for logging
        """
        if self.mode == FilterMode.ALLOWLIST:
            return f"allowlist mode with {len(self.include_ids)} dataset ID(s)"
        else:
            return f"blocklist mode with {len(self.exclude_ids)} dataset ID(s) excluded"

    def get_id_count(self) -> int:
        """
        Get the count of IDs being filtered.

        Returns:
            Number of IDs in the active filter list
        """
        if self.mode == FilterMode.ALLOWLIST:
            return len(self.include_ids)
        else:
            return len(self.exclude_ids)


def _extract_ids_from_section(section: dict | None, section_name: str) -> Set[str]:
    """
    Extract dataset IDs from a config section.

    Args:
        section: The 'include' or 'exclude' section from config
        section_name: Name of section for error messages

    Returns:
        Set of dataset ID strings
    """
    if section is None:
        return set()

    if not isinstance(section, dict):
        raise ConfigError(f"'{section_name}' must be a dictionary, got {type(section).__name__}")

    by_id = section.get('by_id', [])

    if by_id is None:
        return set()

    if not isinstance(by_id, list):
        raise ConfigError(f"'{section_name}.by_id' must be a list, got {type(by_id).__name__}")

    # Convert all IDs to strings and strip whitespace
    ids = set()
    for item in by_id:
        if item is not None:
            id_str = str(item).strip()
            if id_str:
                ids.add(id_str)

    return ids


def validate_config(config: dict, config_path: str) -> None:
    """
    Validate the config structure and values.

    Args:
        config: Parsed YAML config dictionary
        config_path: Path to config file (for error messages)

    Raises:
        ConfigError: If config is invalid
    """
    if not isinstance(config, dict):
        raise ConfigError(f"Config file must contain a YAML dictionary, got {type(config).__name__}")

    # Validate mode
    mode_str = config.get('mode')
    if mode_str is None:
        raise ConfigError("Config file must specify 'mode' (allowlist or blocklist)")

    if not isinstance(mode_str, str):
        raise ConfigError(f"'mode' must be a string, got {type(mode_str).__name__}")

    mode_str = mode_str.lower().strip()
    if mode_str not in ('allowlist', 'blocklist'):
        raise ConfigError(f"Invalid mode '{mode_str}'. Must be 'allowlist' or 'blocklist'")


def load_filter_config(config_path: str) -> DatasetFilter:
    """
    Load and validate a YAML filter config file.

    Args:
        config_path: Path to the YAML config file

    Returns:
        DatasetFilter instance configured according to the file

    Raises:
        ConfigError: If config file is missing, invalid, or has validation errors
        FileNotFoundError: If config file does not exist
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    if not path.is_file():
        raise ConfigError(f"Config path is not a file: {config_path}")

    # Load YAML
    try:
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in config file: {e}")

    if config is None:
        raise ConfigError("Config file is empty")

    # Validate structure
    validate_config(config, config_path)

    # Parse mode
    mode_str = config['mode'].lower().strip()
    mode = FilterMode.ALLOWLIST if mode_str == 'allowlist' else FilterMode.BLOCKLIST

    # Extract IDs
    include_ids = _extract_ids_from_section(config.get('include'), 'include')
    exclude_ids = _extract_ids_from_section(config.get('exclude'), 'exclude')

    # Mode-specific validation and warnings
    if mode == FilterMode.ALLOWLIST:
        # Allowlist mode requires non-empty include list
        if not include_ids:
            raise ConfigError(
                "Allowlist mode requires at least one dataset ID in 'include.by_id'. "
                "An empty allowlist would process nothing."
            )

        # Warn if exclude section is specified (will be ignored)
        if exclude_ids:
            logger.warning(
                f"Config specifies 'exclude' section but mode is 'allowlist'. "
                f"The exclude section ({len(exclude_ids)} IDs) will be ignored."
            )

    else:  # BLOCKLIST mode
        # Warn if exclude list is empty (no filtering will occur)
        if not exclude_ids:
            logger.warning(
                "Blocklist mode with empty 'exclude.by_id' will process all datasets. "
                "This is effectively a no-op filter."
            )

        # Warn if include section is specified (will be ignored)
        if include_ids:
            logger.warning(
                f"Config specifies 'include' section but mode is 'blocklist'. "
                f"The include section ({len(include_ids)} IDs) will be ignored."
            )

    return DatasetFilter(
        mode=mode,
        include_ids=include_ids,
        exclude_ids=exclude_ids
    )
