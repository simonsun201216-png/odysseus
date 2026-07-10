"""
services/data_sync/prophetis.py

Prophetis meeting data sync + hybrid search for Odysseus.

Two components:
  1. MeetingSyncWorker  – background loop that computes embeddings for
     un-embedded meetings and writes them back to Supabase.
  2. MeetingSearchClient – called on each user message to perform hybrid
     FTS+vector search against the Supabase RPC function.

Both communicate with Prophetis's Supabase instance via HTTP (PostgREST),
not through the Prophetis API Gateway — no impact on existing Prophetis
pages or data flows.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import numpy as np

logger = logging.getLogger(__name__)

# ── defaults ──────────────────────────────────────────────────────────────

_DEFAULT_SUPABASE_REST = os.getenv(
    "PROPHETIS_SUPABASE_REST_URL",
    "http://supabase-kong:8000/rest/v1",
)
_DEFAULT_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
_DEFAULT_EMBED_MODEL = os.getenv(
    "PROPHETIS_EMBED_MODEL",
    "BAAI/bge-small-zh-v1.5",  # 512-dim, handles Chinese + English well
)
_SYNC_INTERVAL_SEC = int(os.getenv("PROPHETIS_SYNC_INTERVAL", "30"))
_SYNC_BATCH_SIZE = int(os.getenv("PROPHETIS_SYNC_BATCH", "50"))
_SEARCH_DEFAULT_K = int(os.getenv("PROPHETIS_SEARCH_K", "5"))
_SEARCH_VECTOR_WEIGHT = float(os.getenv("PROPHETIS_VECTOR_WEIGHT", "0.6"))

# ── data types ────────────────────────────────────────────────────────────


@dataclass
class MeetingSearchResult:
    """Single meeting result from hybrid search."""

    uid: str
    main_company: str = ""
    meeting_date: str = ""
    industry: str = ""
    source_tag: str = ""
    source: str = ""
    sentiment: str = ""
    core_summary: str = ""
    key_points: str = ""
    keywords: str = ""
    file_name: str = ""
    vector_score: float = 0.0
    fts_score: float = 0.0
    combined_score: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "MeetingSearchResult":
        return cls(
            uid=d.get("uid") or "",
            main_company=d.get("main_company") or "",
            meeting_date=d.get("meeting_date") or "",
            industry=d.get("industry") or "",
            source_tag=d.get("source_tag") or "",
            source=d.get("source") or "",
            sentiment=d.get("sentiment") or "",
            core_summary=d.get("core_summary") or "",
            key_points=d.get("key_points") or "",
            keywords=d.get("keywords") or "",
            file_name=d.get("file_name") or "",
            vector_score=float(d.get("vector_score") or 0),
            fts_score=float(d.get("fts_score") or 0),
            combined_score=float(d.get("combined_score") or 0),
        )


# ── embedding model (lazy-loaded singleton per process) ───────────────────

_meeting_embedder: Any = None  # fastembed.TextEmbedding instance


def _get_meeting_embedder():
    """Lazy-load the meeting embedding model (Chinese-friendly)."""
    global _meeting_embedder
    if _meeting_embedder is not None:
        return _meeting_embedder

    try:
        from fastembed import TextEmbedding

        cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "fastembed_cache",
        )
        os.makedirs(cache_dir, exist_ok=True)
        _meeting_embedder = TextEmbedding(
            model_name=_DEFAULT_EMBED_MODEL, cache_dir=cache_dir
        )
        logger.info(
            "Meeting embedder loaded: model=%s dim=%d",
            _DEFAULT_EMBED_MODEL,
            _meeting_embedder.embedding_size,
        )
    except Exception as e:
        logger.error("Failed to load meeting embedding model: %s", e)
        _meeting_embedder = None

    return _meeting_embedder


def _meeting_text_to_embed(m: dict) -> str:
    """Build a single searchable text blob from a meeting record for embedding."""
    parts = [
        m.get("core_summary") or "",
        m.get("key_points") or "",
        m.get("keywords") or "",
        m.get("main_company") or "",
        m.get("industry") or "",
        m.get("q_n_a") or "",
        m.get("full_content") or "",
        m.get("sentiment") or "",
    ]
    return "\n".join(p for p in parts if p.strip())


# ── HTTP client helpers ───────────────────────────────────────────────────

_REST_HEADERS = {
    "apikey": _DEFAULT_SERVICE_KEY,
    "Authorization": f"Bearer {_DEFAULT_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

async def _rest_get(
    client: httpx.AsyncClient, path: str, params: dict
) -> list[dict]:
    """GET from Supabase PostgREST and return JSON data."""
    resp = await client.get(
        f"{_DEFAULT_SUPABASE_REST}{path}",
        headers=_REST_HEADERS,
        params=params,
    )
    resp.raise_for_status()
    return resp.json()


async def _rest_upsert(
    client: httpx.AsyncClient, path: str, data: dict
) -> None:
    """UPSERT a record in Supabase PostgREST (POST + merge-duplicates).

    Uses ``Prefer: resolution=merge-duplicates`` so a row with the same
    primary key is updated rather than duplicated.
    """
    headers = {
        **_REST_HEADERS,
        "Prefer": "resolution=merge-duplicates",
    }
    resp = await client.post(
        f"{_DEFAULT_SUPABASE_REST}{path}",
        headers=headers,
        json=data,
    )
    resp.raise_for_status()


async def _rest_rpc(
    client: httpx.AsyncClient, rpc_name: str, params: dict
) -> list[dict]:
    """Call a Supabase RPC function."""
    resp = await client.post(
        f"{_DEFAULT_SUPABASE_REST}/rpc/{rpc_name}",
        headers=_REST_HEADERS,
        json=params,
    )
    resp.raise_for_status()
    return resp.json()


# ── MeetingSyncWorker: background embedding sync ──────────────────────────


class MeetingSyncWorker:
    """Background worker that computes embeddings for new meetings.

    Finds meetings that lack an entry in the separate ``meeting_embeddings``
    table, generates embeddings via local FastEmbed, and UPSERTS them into
    that table. The ``meetings`` table itself is never modified.

    Uses cursor-based ascending pagination (``updated_at.asc,uid.asc``) so
    that ALL meetings — not just the most recent — eventually get embedded.
    The cursor is persisted in-memory across sync cycles.

    Runs every ``_SYNC_INTERVAL_SEC`` seconds. Safe to run from startup
    — handles missing services, rate-limiting, and partial failures.
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._cursor: Optional[str] = None  # ISO timestamp for pagination

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    async def _existing_embedding_uids(self, client: httpx.AsyncClient) -> set:
        """Fetch the set of meeting UIDs that already have embeddings."""
        try:
            rows = await _rest_get(
                client,
                "/meeting_embeddings",
                params={"select": "uid"},
            )
            return {r["uid"] for r in rows}
        except Exception as e:
            logger.warning("Failed to fetch existing embedding UIDs: %s", e)
            # If the table doesn't exist yet (DDL not run), return empty set
            # so the sync proceeds and logs clear diagnostics on first try.
            return set()

    async def sync_once(self) -> int:
        """Fetch the next batch of un-embedded meetings, embed, and upsert.

        Uses cursor-based ascending pagination so every meeting — not just
        the most recent — eventually gets an embedding.

        Returns:
            Number of meetings successfully updated.
        """
        embedder = _get_meeting_embedder()
        if embedder is None:
            logger.warning("Meeting embedder not available — skipping sync")
            return 0

        client = await self._ensure_client()

        # 1. Get UIDs that already have embeddings
        existing_uids = await self._existing_embedding_uids(client)

        # 2. Fetch candidate meetings ordered oldest-first with cursor
        fetch_limit = _SYNC_BATCH_SIZE * 2
        params: dict[str, str] = {
            "select": (
                "uid,updated_at,core_summary,key_points,keywords,main_company,"
                "industry,q_n_a,full_content,sentiment"
            ),
            "limit": str(fetch_limit),
            "order": "updated_at.asc,uid.asc",
        }
        if self._cursor is not None:
            params["updated_at"] = f"gt.{self._cursor}"

        try:
            meetings = await _rest_get(client, "/meetings", params)
        except Exception as e:
            logger.warning("Failed to fetch meetings: %s", e)
            return 0

        if not meetings:
            # Reached the end of the table — reset cursor so new meetings
            # are picked up on subsequent cycles.
            logger.info(
                "Meeting sync: reached end of table (cursor=%s), resetting",
                self._cursor,
            )
            self._cursor = None
            return 0

        # 3. Filter to only un-embedded meetings
        rows = [m for m in meetings if m["uid"] not in existing_uids][:_SYNC_BATCH_SIZE]

        if not rows:
            # All meetings in this batch are already embedded — advance cursor
            # past this batch to find un-embedded ones further down.
            last_ts = meetings[-1]["updated_at"]
            if last_ts == self._cursor:
                # Safety: cursor hasn't budged (e.g. many rows share a
                # timestamp). Reset to break the loop — missed rows will be
                # caught on a full scan when the cursor resets at the end.
                logger.warning(
                    "Sync cursor stuck at %s — resetting", last_ts,
                )
                self._cursor = None
            else:
                self._cursor = last_ts
            return 0

        # 4. Build text blobs and embed in batch
        texts = [_meeting_text_to_embed(r) for r in rows]
        try:
            embeddings: list[np.ndarray] = list(
                embedder.passage_embed(texts)
            )
        except Exception as e:
            logger.error("Batch embedding failed: %s", e)
            return 0

        # 5. UPSERT each embedding into the separate meeting_embeddings table
        updated = 0
        for row, emb in zip(rows, embeddings):
            uid = row.get("uid")
            if not uid:
                continue
            try:
                await _rest_upsert(
                    client,
                    "/meeting_embeddings",
                    {"uid": uid, "embedding": emb.tolist()},
                )
                updated += 1
            except Exception as e:
                logger.warning("Failed to upsert embedding for %s: %s", uid, e)

        # 6. Advance cursor past the processed batch
        self._cursor = meetings[-1]["updated_at"]

        if updated:
            logger.info(
                "Meeting sync: %d/%d upserted "
                "(total_embedded=%d, cursor=%.23s)",
                updated,
                len(rows),
                len(existing_uids) + updated,
                self._cursor or "reset",
            )

        return updated

    async def run_loop(self):
        """Continuous background loop — call from app startup."""
        logger.info(
            "Meeting sync worker started (interval=%ds, batch=%d)",
            _SYNC_INTERVAL_SEC,
            _SYNC_BATCH_SIZE,
        )
        while True:
            try:
                await self.sync_once()
            except asyncio.CancelledError:
                logger.info("Meeting sync worker cancelled")
                break
            except Exception as e:
                logger.warning("Meeting sync worker error: %s", e)
            await asyncio.sleep(_SYNC_INTERVAL_SEC)


# ── MeetingSearchClient: hybrid search for chat context ───────────────────


class MeetingSearchClient:
    """Hybrid search client for Prophetis meetings.

    Called from chat_processor to retrieve relevant meetings as RAG context.
    Uses the ``search_meetings`` Supabase RPC function (FTS + pgvector).
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client

    async def search(
        self,
        query: str,
        k: int = _SEARCH_DEFAULT_K,
        vector_weight: float = _SEARCH_VECTOR_WEIGHT,
        company_filter: Optional[str] = None,
        industry_filter: Optional[str] = None,
        source_filter: Optional[str] = None,
    ) -> list[MeetingSearchResult]:
        """Hybrid search (FTS + vector) against Prophetis meetings.

        If the embedding model is unavailable or the RPC call fails,
        falls back to FTS-only via the Prophetis API Gateway.
        """
        if not query.strip():
            return []

        embedder = _get_meeting_embedder()
        query_embedding: Optional[list[float]] = None

        # Generate query embedding if model is available
        if embedder is not None:
            try:
                emb_iter = embedder.query_embed(query)
                query_embedding = next(emb_iter).tolist()
            except Exception as e:
                logger.debug("Query embedding failed (FTS fallback): %s", e)

        client = await self._ensure_client()

        # Build RPC params
        rpc_params: dict[str, Any] = {
            "p_query_text": query,
            "p_match_count": k,
        }
        if query_embedding is not None:
            rpc_params["p_query_embedding"] = query_embedding
        else:
            # Pass null array — function handles embedding IS NULL gracefully
            rpc_params["p_query_embedding"] = None

        rpc_params["p_vector_weight"] = vector_weight

        if company_filter:
            rpc_params["p_company_filter"] = company_filter
        if industry_filter:
            rpc_params["p_industry_filter"] = industry_filter
        if source_filter:
            rpc_params["p_source_filter"] = source_filter

        # Try Supabase RPC first
        try:
            rows = await _rest_rpc(client, "search_meetings", rpc_params)
            if rows:
                results = [MeetingSearchResult.from_dict(r) for r in rows]
                logger.debug(
                    "Meetings hybrid search: %d results (query=%.40s)",
                    len(results),
                    query,
                )
                return results
        except Exception as e:
            logger.debug(
                "Meetings RPC search failed (%s) — will try API fallback", e
            )

        # FTS-only fallback via Prophetis API Gateway
        try:
            return await self._api_search_fallback(query, k)
        except Exception as e:
            logger.warning("Meetings API fallback also failed: %s", e)
            return []

    async def _api_search_fallback(
        self, query: str, k: int
    ) -> list[MeetingSearchResult]:
        """Fallback: search via Prophetis API Gateway FTS (keyword filter)."""
        api_gw_url = os.getenv(
            "PROPHETIS_API_GW_URL",
            "http://api-gw:28000",
        )
        params = {"keyword": query, "limit": str(k)}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0)
        ) as fallback_client:
            resp = await fallback_client.get(
                f"{api_gw_url}/v1/meetings", params=params
            )
            resp.raise_for_status()
            data = resp.json()
            meetings = data if isinstance(data, list) else data.get("data", [])

        results = []
        for m in meetings:
            results.append(
                MeetingSearchResult(
                    uid=m.get("uid") or "",
                    main_company=m.get("main_company") or "",
                    meeting_date=m.get("meeting_date") or "",
                    industry=m.get("industry") or "",
                    source_tag=m.get("source_tag") or "",
                    source=m.get("source") or "",
                    sentiment=m.get("sentiment") or "",
                    core_summary=m.get("core_summary") or "",
                    key_points=m.get("key_points") or "",
                    keywords=m.get("keywords") or "",
                    file_name=m.get("file_name") or "",
                )
            )
        return results

    def format_for_context(self, results: list[MeetingSearchResult]) -> str:
        """Format meeting results as a context string for LLM injection."""
        if not results:
            return ""

        lines = [
            "--- Prophetis Meeting Intelligence ---",
            "Relevant meeting records from your financial research database:",
        ]
        for i, r in enumerate(results, 1):
            lines.append("")
            lines.append(f"  [{i}] {r.main_company} ({r.meeting_date})")
            if r.industry:
                lines.append(f"      Industry: {r.industry}")
            if r.source_tag:
                lines.append(f"      Source: {r.source_tag}")
            if r.sentiment:
                lines.append(f"      Sentiment: {r.sentiment}")
            if r.keywords:
                lines.append(f"      Keywords: {r.keywords}")
            if r.core_summary:
                lines.append(f"      Summary: {r.core_summary[:300]}")
            if r.key_points:
                lines.append(f"      Key Points: {r.key_points[:300]}")
            if r.combined_score > 0:
                lines.append(
                    f"      Relevance: {r.combined_score:.2f}"
                )
        return "\n".join(lines)


# ── ProphetisMeetingService: unified facade ───────────────────────────────


class ProphetisMeetingService:
    """Unified entry-point for Prophetis meeting data.

    Combines the sync worker (background embedding generation) and search
    client (hybrid retrieval for chat). Instantiated once by app startup
    and stored in ``app.state.prophetis_meetings``.
    """

    def __init__(self):
        self.sync_worker = MeetingSyncWorker()
        self.search_client = MeetingSearchClient()
        self._healthy = False

    async def search(
        self, query: str, k: int = _SEARCH_DEFAULT_K, **kwargs
    ) -> list[MeetingSearchResult]:
        """Hybrid search delegating to MeetingSearchClient."""
        return await self.search_client.search(query, k=k, **kwargs)

    def search_sync(
        self,
        query: str,
        k: int = _SEARCH_DEFAULT_K,
        vector_weight: float = _SEARCH_VECTOR_WEIGHT,
        company_filter: Optional[str] = None,
        industry_filter: Optional[str] = None,
        source_filter: Optional[str] = None,
    ) -> list[MeetingSearchResult]:
        """Synchronous hybrid search for non-async callers (e.g. chat_processor).

        Falls back to FTS-only via API Gateway if vector search is unavailable.
        """
        if not query.strip():
            return []

        embedder = _get_meeting_embedder()
        query_embedding: Optional[list[float]] = None

        if embedder is not None:
            try:
                emb_iter = embedder.query_embed(query)
                query_embedding = next(emb_iter).tolist()
            except Exception as e:
                logger.debug("Query embedding failed (sync, FTS fallback): %s", e)

        # Build RPC params
        rpc_params: dict[str, Any] = {
            "p_query_text": query,
            "p_match_count": k,
            "p_query_embedding": query_embedding,
            "p_vector_weight": vector_weight,
        }
        if company_filter:
            rpc_params["p_company_filter"] = company_filter
        if industry_filter:
            rpc_params["p_industry_filter"] = industry_filter
        if source_filter:
            rpc_params["p_source_filter"] = source_filter

        # Try Supabase RPC (synchronous)
        try:
            with httpx.Client(timeout=httpx.Timeout(15.0)) as c:
                resp = c.post(
                    f"{_DEFAULT_SUPABASE_REST}/rpc/search_meetings",
                    headers=_REST_HEADERS,
                    json=rpc_params,
                )
                resp.raise_for_status()
                rows = resp.json()
            if rows:
                results = [MeetingSearchResult.from_dict(r) for r in rows]
                logger.info(
                    "Meetings sync search: %d results (query=%.40s)",
                    len(results), query,
                )
                return results
        except Exception as e:
            logger.info("Meetings sync RPC failed (%s) — API fallback", e)

        # FTS fallback via API Gateway
        try:
            return self._api_search_fallback_sync(query, k)
        except Exception as e:
            logger.warning("Meetings sync API fallback failed: %s", e)
            return []

    def _api_search_fallback_sync(
        self, query: str, k: int
    ) -> list[MeetingSearchResult]:
        """Synchronous fallback via Prophetis API Gateway FTS."""
        api_gw_url = os.getenv(
            "PROPHETIS_API_GW_URL", "http://api-gw:28000",
        )
        with httpx.Client(timeout=httpx.Timeout(10.0)) as c:
            resp = c.get(
                f"{api_gw_url}/v1/meetings",
                params={"keyword": query, "limit": str(k)},
            )
            resp.raise_for_status()
            data = resp.json()
            meetings = data if isinstance(data, list) else data.get("data", [])
        return [
            MeetingSearchResult(
                uid=m.get("uid") or "",
                main_company=m.get("main_company") or "",
                meeting_date=m.get("meeting_date") or "",
                industry=m.get("industry") or "",
                source_tag=m.get("source_tag") or "",
                source=m.get("source") or "",
                sentiment=m.get("sentiment") or "",
                core_summary=m.get("core_summary") or "",
                key_points=m.get("key_points") or "",
                keywords=m.get("keywords") or "",
                file_name=m.get("file_name") or "",
            )
            for m in meetings
        ]

    def get_recent_meetings(
        self, k: int = 15,
    ) -> list[MeetingSearchResult]:
        """Fetch the most recent N meetings by ``meeting_date`` (synchronous).

        Used alongside query-based search so that blanket queries like
        "summarise all meetings from the past 3 days" still have data to work
        with, even when the FTS+vector search doesn't return recent records.

        Returns:
            List of ``MeetingSearchResult`` ordered by meeting_date desc.
        """
        select = (
            "uid,meeting_date,main_company,industry,source_tag,source,"
            "sentiment,core_summary,key_points,keywords,file_name"
        )
        params = {
            "select": select,
            "order": "meeting_date.desc",
            "limit": str(k),
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(15.0)) as c:
                resp = c.get(
                    f"{_DEFAULT_SUPABASE_REST}/meetings",
                    headers=_REST_HEADERS,
                    params=params,
                )
                resp.raise_for_status()
                rows = resp.json()
            return [MeetingSearchResult.from_dict(r) for r in rows]
        except Exception as e:
            logger.warning("Failed to fetch recent meetings: %s", e)
            return []

    def format_context(
        self, results: list[MeetingSearchResult]
    ) -> str:
        """Format results for LLM context injection (legacy)."""
        return self.search_client.format_for_context(results)

    def format_context_with_sources(
        self, results: list[MeetingSearchResult]
    ) -> str:
        """Format results for LLM context injection with source_id tracking.

        L1 mode: always includes full core_summary + key_points (no truncation).
        Each result includes source_id for citation.
        """
        if not results:
            return ""

        lines = [
            "--- Prophetis Meeting Intelligence ---",
            "Relevant meeting records from your financial research database.",
            "IMPORTANT — SOURCE CITATION RULES:",
            "  - Each record has a Source ID. CITE these when answering.",
            "  - Format: [claim] (source_XXXXXXXX)",
            "  - Example: \"电动化市占率从15%提升至22%（source_b0620259）\"",
            "  - Multiple sources: cite all that support the claim.",
            "  - Uncited claims will be treated as speculation.",
            "",
        ]
        for i, r in enumerate(results, 1):
            source_id = getattr(r, "source_id", None) or f"source_{r.uid[:8]}" if r.uid else f"result_{i}"
            lines.append(f"  [{i}] Source: {source_id}")
            lines.append(f"      Company: {r.main_company or r.company or ''}")
            lines.append(f"      Date: {r.meeting_date}")
            if r.industry:
                lines.append(f"      Industry: {r.industry}")
            if r.source_tag:
                lines.append(f"      Source Tag: {r.source_tag}")
            if r.sentiment:
                lines.append(f"      Sentiment: {r.sentiment}")
            if hasattr(r, "keywords_clean") and r.keywords_clean:
                lines.append(f"      Keywords: {r.keywords_clean}")
            elif r.keywords:
                lines.append(f"      Keywords: {r.keywords}")
            if r.core_summary:
                lines.append(f"      Summary: {r.core_summary}")
            if r.key_points:
                lines.append(f"      Key Points: {r.key_points}")
            if r.combined_score > 0:
                lines.append(f"      Relevance: {r.combined_score:.2f}")
            lines.append("")
        return "\n".join(lines)

    @property
    def healthy(self) -> bool:
        return self._healthy

    async def health_check(self) -> bool:
        """Ping the Supabase REST endpoint to verify connectivity."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0)
            ) as c:
                resp = await c.get(
                    f"{_DEFAULT_SUPABASE_REST}/meetings",
                    headers=_REST_HEADERS,
                    params={"select": "uid", "limit": "1"},
                )
                self._healthy = resp.is_success
        except Exception:
            self._healthy = False
        return self._healthy

    # Convenience: start the background sync loop
    async def start_sync_loop(self):
        """Start the background embedding sync loop (fire-and-forget)."""
        asyncio.create_task(self.sync_worker.run_loop())
