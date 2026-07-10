# services/data_sync/__init__.py
"""Data-source sync layer — one-way inbound sync from external systems."""

from .prophetis import (
    ProphetisMeetingService,
    MeetingSyncWorker,
    MeetingSearchResult,
    MeetingSearchClient,
)
from .kb_client import (
    KnowledgeBaseClient,
    KBSearchResult,
)

__all__ = [
    "ProphetisMeetingService",
    "MeetingSyncWorker",
    "MeetingSearchResult",
    "MeetingSearchClient",
    "KnowledgeBaseClient",
    "KBSearchResult",
]
