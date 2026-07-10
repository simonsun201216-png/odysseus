"""Skills discovery service — find, parse, and rank skills from external sources."""

from .discoverer import (
    SkillsDiscoveryService,
    KNOWN_SOURCES,
    DEFAULT_SEARCH_QUERIES,
)

__all__ = [
    "SkillsDiscoveryService",
    "KNOWN_SOURCES",
    "DEFAULT_SEARCH_QUERIES",
]
