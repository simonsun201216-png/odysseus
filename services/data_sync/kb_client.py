"""
services/data_sync/kb_client.py

Knowledge Base client — structured query API for the kb_ normalized data layer.

Provides:
  - search(): hybrid FTS+vector+time-decay search via kb.search_meetings_v2
  - lookup_by_source_id(): traceability back to raw meeting record
  - timeline(): time-series aggregation for a company/keyword
  - format_context(): format results for LLM injection with source tracking
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

try:
    from fastembed import TextEmbedding
    _HAS_FASTEMBED = True
except ImportError:
    _HAS_FASTEMBED = False
    TextEmbedding = None  # type: ignore

logger = logging.getLogger(__name__)

_DEFAULT_SUPABASE_REST = os.getenv(
    "PROPHETIS_SUPABASE_REST_URL",
    "http://supabase-kong:8000/rest/v1",
)
_DEFAULT_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
_REST_HEADERS = {
    "apikey": _DEFAULT_SERVICE_KEY,
    "Authorization": f"Bearer {_DEFAULT_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


# ── Data types ──────────────────────────────────────────────────────────────


@dataclass
class KBSearchResult:
    """Single result from kb.search_meetings_v2."""

    source_id: str = ""
    uid: str = ""
    company: str = ""
    meeting_date: str = ""
    industry: str = ""
    source_tag: str = ""
    sentiment_val: Optional[int] = None
    sentiment_raw: str = ""
    keywords_clean: str = ""
    core_summary: str = ""
    key_points: str = ""
    full_content: str = ""
    q_n_a: str = ""
    vector_score: float = 0.0
    fts_score: float = 0.0
    time_score: float = 0.0
    combined_score: float = 0.0
    match_type: str = "keyword_match"  # "keyword_match" | "semantic_discovery"
    # full_doc fields
    file_name: str = ""
    mentioned_companies: str = ""

    @property
    def meeting_url(self) -> str:
        """Frontend URL to view this meeting's detail page."""
        if self.uid:
            return f"/meetings?uid={self.uid}"
        return ""

    @classmethod
    def from_dict(cls, d: dict) -> "KBSearchResult":
        return cls(
            source_id=d.get("source_id") or "",
            uid=d.get("uid") or "",
            company=d.get("company") or "",
            meeting_date=str(d.get("meeting_date") or ""),
            industry=d.get("industry") or "",
            source_tag=d.get("source_tag") or "",
            sentiment_val=d.get("sentiment_val"),
            sentiment_raw=d.get("sentiment_raw") or "",
            keywords_clean=d.get("keywords_clean") or "",
            core_summary=d.get("core_summary") or "",
            key_points=d.get("key_points") or "",
            full_content=d.get("full_content") or "",
            q_n_a=d.get("q_n_a") or "",
            vector_score=float(d.get("vector_score") or 0),
            fts_score=float(d.get("fts_score") or 0),
            time_score=float(d.get("time_score") or 0),
            combined_score=float(d.get("combined_score") or 0),
            file_name=d.get("file_name") or "",
            mentioned_companies=d.get("mentioned_companies") or "",
        )

    def to_rag_chunk(self) -> dict:
        """Convert to RAG context chunk with source tracking."""
        return {
            "source_id": self.source_id,
            "uid": self.uid,
            "company": self.company,
            "meeting_date": self.meeting_date,
            "source_tag": self.source_tag,
            "sentiment": f"{self.sentiment_val:+d}" if self.sentiment_val is not None else "N/A",
            "keywords": self.keywords_clean,
            "summary": self.core_summary,
            "key_points": self.key_points,
            "relevance": round(self.combined_score, 3),
        }


# ── KB Client ──────────────────────────────────────────────────────────────


class KnowledgeBaseClient:
    """Structured query client for the kb_ layer via Supabase RPC."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._embed_model = None

    # ── Embedding ──

    _EMBED_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
    _EMBED_DIM = 512

    def _get_embed_model(self):
        """Lazy-load the multilingual embedding model on first use.

        Uses BAAI/bge-m3 (multilingual, 1024-dim) supporting:
          Chinese, English, Japanese, Korean, Traditional Chinese, and 100+ languages.
        """
        if self._embed_model is None:
            if not _HAS_FASTEMBED:
                raise RuntimeError(
                    "fastembed not installed. Run: pip install fastembed"
                )
            logger.info("Loading embedding model: %s (multilingual 1024-dim)", self._EMBED_MODEL_NAME)
            self._embed_model = TextEmbedding(
                model_name=self._EMBED_MODEL_NAME,
                max_length=8192,  # bge-m3 supports up to 8192 tokens
            )
        return self._embed_model

    def _compute_embedding(self, text: str) -> list[float]:
        """Compute 1024-dim embedding vector for text.

        Uses fastembed + BAAI/bge-m3 (multilingual: CN, EN, JP, KR, etc.).
        Returns a plain list of floats suitable for pgvector.
        """
        if not text or not text.strip():
            return []
        model = self._get_embed_model()
        embedding = next(model.embed([text]))
        return embedding.tolist()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    async def _rpc(self, fn_name: str, params: dict) -> list[dict]:
        client = await self._ensure_client()
        resp = await client.post(
            f"{_DEFAULT_SUPABASE_REST}/rpc/{fn_name}",
            headers=_REST_HEADERS,
            json=params,
        )
        resp.raise_for_status()
        return resp.json()

    async def decompose_query(
        self, query: str
    ) -> dict[str, list[str]]:
        """Decompose a natural language query into structured search params.

        Calls kb.decompose_query RPC which extracts:
          - companies: known company names matched from 36k+ aliases
          - industries: matched from 20 clean industry categories
          - keywords: remainder after entity subtraction

        Returns:
            dict with keys: companies, industries, keywords (each a list of strings)
        """
        if not query or not query.strip():
            return {"companies": [], "industries": [], "keywords": []}

        try:
            rows = await self._rpc("decompose_query", {"p_query": query})
        except Exception as e:
            logger.warning("Query decomposition failed: %s", e)
            return {"companies": [], "industries": [], "keywords": []}

        result: dict[str, list[str]] = {
            "companies": [],
            "industries": [],
            "keywords": [],
        }
        for row in rows:
            etype = row.get("entity_type", "")
            evalue = row.get("entity_value", "")
            if etype == "company":
                result["companies"].append(evalue)
            elif etype == "industry":
                result["industries"].append(evalue)
            elif etype == "keyword":
                result["keywords"].append(evalue)

        if result["companies"] or result["industries"] or result["keywords"]:
            logger.info(
                "Query decomposed: companies=%s industries=%s keywords=%s",
                result["companies"], result["industries"], result["keywords"],
            )
        return result

    async def search(
        self,
        query: str = "",
        query_embedding: Optional[list[float]] = None,
        auto_decompose: bool = True,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        companies: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        source_tags: Optional[list[str]] = None,
        mode: str = "scan",
        k: int = 10,
        vector_weight: float = 0.4,
        min_score: float = 0.0,
    ) -> list[KBSearchResult]:
        """Structured hybrid search against kb.search_meetings_v2.

        Args:
            query: Natural language query text (FTS-matched)
            query_embedding: Optional 512-dim embedding vector
            date_from: ISO date string (inclusive)
            date_to: ISO date string (inclusive)
            companies: Filter to meetings mentioning these companies
            industries: Filter to meetings in these industry categories
            keywords: Filter to meetings with these keywords
            source_tags: Filter by source (COMIN, 3B, PLE, TW, Youtube)
            mode: 'scan' (summary only) or 'deep_dive' (full content)
            k: Max results
            vector_weight: Weight for vector similarity (0-1)
            min_score: Minimum combined score threshold

        Returns:
            List of KBSearchResult sorted by combined_score descending.
        """
        # Auto-compute embedding if text query is given but no pre-computed embedding.
        # This enables vector search alongside FTS. Falls back gracefully on error.
        if not query_embedding and query.strip():
            try:
                query_embedding = self._compute_embedding(query)
                logger.debug("Computed embedding (dim=%d) for query: %.40s",
                             len(query_embedding), query)
            except Exception as e:
                logger.warning("Embedding unavailable (FTS-only): %s", e)

        # Auto-decompose query into structured params when caller didn't
        # provide explicit companies/industries/keywords.
        # The decomposed companies/industries/keywords are used as filters,
        # and the keyword remainder becomes the effective query text for FTS.
        if auto_decompose and query.strip():
            if not companies and not industries and not keywords:
                decomposed = await self.decompose_query(query)
                companies = decomposed["companies"] or None
                industries = decomposed["industries"] or None
                keywords_from_decomp = decomposed["keywords"] or None
                if keywords_from_decomp:
                    # Use the decomposed keyword (entity-reduced) as the
                    # query text for better FTS matching
                    query_text_effective = " ".join(keywords_from_decomp)
                else:
                    query_text_effective = query
                # If we have company/industry filters but no keyword,
                # use a generic query text to avoid FTS over-filtering
                if (companies or industries) and not keywords_from_decomp:
                    query_text_effective = ""  # empty = no FTS filter
                # Only override query if we have structured params
                if companies or industries:
                    query = query_text_effective or query

        params: dict[str, Any] = {
            "p_query_text": query,
            "p_mode": mode,
            "p_match_count": k,
            "p_vector_weight": vector_weight,
            "p_min_score": min_score,
        }
        if query_embedding:
            params["p_query_embedding"] = query_embedding
        if date_from:
            params["p_date_from"] = date_from
        if date_to:
            params["p_date_to"] = date_to
        if companies:
            params["p_companies"] = companies
        if industries:
            params["p_industries"] = industries
        if keywords:
            params["p_keyword_filter"] = keywords
        if source_tags:
            params["p_source_tags"] = source_tags

        try:
            rows = await self._rpc("search_meetings_v2", params)
            return [KBSearchResult.from_dict(r) for r in rows]
        except Exception as e:
            logger.warning("KB search failed: %s", e)
            return []

    async def deep_search(
        self,
        query: str = "",
        k: int = 30,
        min_score: float = 0.0,
        mode: str = "full_doc",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[KBSearchResult]:
        """Deep KB research: multi-angle search with query decomposition.

        For complex research queries, this method:
        1. Decomposes the query into companies, industries, keywords
        2. Runs primary FTS+vector search
        3. Runs additional searches for each extracted entity
        4. Includes recent meetings for context
        5. Merges & deduplicates all results

        Args:
            query: Research question
            k: Max results per sub-search
            min_score: Minimum relevance threshold
            mode: 'full_doc' for complete records
            date_from/to: Optional date filter

        Returns:
            Merged, deduplicated list of KBSearchResult sorted by relevance.
        """
        if not query or not query.strip():
            # No query: just return recent meetings sorted by date
            return await self.search(query="", mode=mode, k=k, min_score=0.0)

        seen_uids: set = set()
        all_results: list[KBSearchResult] = []

        def _add(results: list[KBSearchResult]):
            for r in results:
                if r.uid and r.uid not in seen_uids:
                    seen_uids.add(r.uid)
                    all_results.append(r)

        # Phase 1: Primary search (FTS + vector)
        primary = await self.search_with_complement(
            query=query, k=max(k // 2, 10),
            min_score=min_score, mode=mode,
        )
        _add(primary)
        logger.info("DeepSearch phase1 (primary): %d unique", len(primary))

        # Phase 2: Decompose query and search each entity
        try:
            decomposed = await self.decompose_query(query)
            companies = decomposed.get("companies", [])
            industries = decomposed.get("industries", [])
            keywords = decomposed.get("keywords", [])

            # Search by extracted companies
            for company in companies[:5]:
                try:
                    cr = await self.search(
                        query=company, mode=mode, k=k // 3,
                        min_score=min_score,
                        date_from=date_from, date_to=date_to,
                    )
                    _add(cr)
                except Exception:
                    continue

            # Search by extracted industries
            for industry in industries[:3]:
                try:
                    ir = await self.search(
                        query=industry, mode=mode, k=k // 3,
                        min_score=min_score,
                        date_from=date_from, date_to=date_to,
                    )
                    _add(ir)
                except Exception:
                    continue

            # Search by extracted keywords
            if keywords:
                kw_query = " ".join(keywords[:5])
                kw_results = await self.search(
                    query=kw_query, mode=mode, k=k // 2,
                    min_score=min_score,
                    date_from=date_from, date_to=date_to,
                )
                _add(kw_results)

            logger.info(
                "DeepSearch phase2 (decompose): %d companies + %d industries + %d keywords → %d new",
                len(companies), len(industries), len(keywords),
                len(all_results) - len(primary),
            )
        except Exception as e:
            logger.warning("DeepSearch phase2 failed: %s", e)

        # Phase 3: Recent meetings for context
        try:
            recent = await self.search(
                query="", mode=mode, k=k // 2, min_score=0.0,
            )
            _add(recent)
            logger.info("DeepSearch phase3 (recent): %d new", len(recent))
        except Exception as e:
            logger.warning("DeepSearch phase3 failed: %s", e)

        # Sort by combined_score descending
        all_results.sort(key=lambda r: r.combined_score, reverse=True)
        logger.info(
            "DeepSearch total: %d unique results from %d phases",
            len(all_results), 3,
        )
        return all_results[:k]

    async def search_with_complement(
        self,
        query: str = "",
        k: int = 10,
        min_score: float = 0.0,
        mode: str = "scan",
        **kwargs,
    ) -> list[KBSearchResult]:
        """Hybrid search with complement detection.

        Runs two searches:
          1. FTS-based search (precision) → keyword_match results
          2. Pure vector search (recall) → semantic_discovery results

        Merges results: FTS first, then up to 3 semantic discoveries
        that the FTS missed.

        Args:
            query: Natural language query
            k: Number of FTS results
            min_score: Minimum relevance threshold
            mode: 'scan' or 'deep_dive'
            **kwargs: Passed through to search() (source_tags, date filters, etc.)

        Returns:
            List of KBSearchResult with match_type set appropriately.
        """
        if not query or not query.strip():
            return await self.search(
                query="", k=k, min_score=min_score, mode=mode,
                auto_decompose=False, **kwargs
            )

        # Step 1: FTS search (with decomposition)
        fts_results = await self.search(
            query=query, k=k, min_score=min_score, mode=mode,
            auto_decompose=True, **kwargs
        )
        fts_uids = {r.uid for r in fts_results}
        for r in fts_results:
            r.match_type = "keyword_match"

        # Step 2: Vector-only search (semantic complement)
        discovery_results: list[KBSearchResult] = []
        try:
            embedding = self._compute_embedding(query)
            if embedding:
                # Pure vector search: empty query text so FTS doesn't filter
                vector_results = await self.search(
                    query="",
                    query_embedding=embedding,
                    k=k * 2,
                    min_score=0.0,
                    mode=mode,
                    auto_decompose=False,
                )
                # Complement = vector results not found by FTS
                discovery_results = [
                    r for r in vector_results
                    if r.uid not in fts_uids
                ]
                for r in discovery_results:
                    r.match_type = "semantic_discovery"
                if discovery_results:
                    logger.info(
                        "Complement detection: %d semantic discoveries (k=%d FTS results)",
                        len(discovery_results), len(fts_results),
                    )
        except Exception as e:
            logger.warning("Vector complement search failed (FTS-only): %s", e)

        # Step 3: Merge — FTS results first, then up to 3 discoveries
        merged = list(fts_results)
        merged.extend(discovery_results[:3])
        return merged

    async def lookup_by_source_id(
        self, source_id: str
    ) -> Optional[dict]:
        """Trace back from source_id to full raw meeting record.

        Returns full public.meetings record or None if not found.
        """
        try:
            rows = await self._rpc("lookup_by_source_id", {
                "p_source_id": source_id,
            })
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning("KB source lookup failed: %s", e)
        return None

    async def timeline(
        self,
        company: Optional[str] = None,
        keyword: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        interval: str = "month",
    ) -> list[dict]:
        """Time-series aggregation.

        Returns time-bucketed data points with meeting counts, avg sentiment,
        and top keywords for each interval.

        Args:
            company: Company to trace
            keyword: Keyword to trace
            date_from: ISO date string
            date_to: ISO date string
            interval: 'month' or 'quarter'
        """
        # Use the v2 search to get candidate results, then aggregate in Python
        results = await self.search(
            query=keyword or "",
            companies=[company] if company else None,
            keywords=[keyword] if keyword and not company else None,
            date_from=date_from,
            date_to=date_to,
            mode="scan",
            k=500,  # Get many results for aggregation
            min_score=0.0,
        )

        if not results:
            return []

        import calendar
        from collections import defaultdict

        buckets: dict[str, list[KBSearchResult]] = defaultdict(list)

        for r in results:
            if not r.meeting_date:
                continue
            parts = r.meeting_date.split("-")
            if len(parts) < 2:
                continue
            year, month = parts[0], parts[1].zfill(2)
            if interval == "quarter":
                q = str((int(month) - 1) // 3 + 1)
                key = f"{year}-Q{q}"
            else:
                key = f"{year}-{month}"

            buckets[key].append(r)

        timeline_data = []
        for key in sorted(buckets.keys()):
            items = buckets[key]
            sentiments = [
                r.sentiment_val
                for r in items
                if r.sentiment_val is not None
            ]
            top_keywords: dict[str, int] = {}
            for r in items:
                for kw in r.keywords_clean.split(", "):
                    kw = kw.strip()
                    if kw and len(kw) > 1:
                        top_keywords[kw] = top_keywords.get(kw, 0) + 1

            timeline_data.append({
                "period": key,
                "meeting_count": len(items),
                "avg_sentiment": (
                    round(sum(sentiments) / len(sentiments), 2)
                    if sentiments else None
                ),
                "top_keywords": sorted(
                    top_keywords.items(), key=lambda x: -x[1]
                )[:10],
                "companies": list(set(
                    r.company for r in items if r.company
                ))[:20],
            })

        return timeline_data

    def format_for_context(
        self, results: list[KBSearchResult], mode: str = "scan"
    ) -> str:
        """Format search results as LLM context with source tracking.

        scan mode (default): summary + key_points only
        deep_dive mode: includes full_content and q_n_a
        full_doc mode: ALL raw fields including file_name, mentioned_companies, etc.
        """
        if not results:
            return ""

        n_keyword = sum(1 for r in results if r.match_type == "keyword_match")
        n_discovery = sum(1 for r in results if r.match_type == "semantic_discovery")

        lines = [
            "--- Prophetis Knowledge Base Results ---",
            "Relevant meeting records from your proprietary financial research database.",
            "",
            "RETRIEVAL METHOD:",
            f"  - keyword_match ({n_keyword}): precise keyword/database search",
            f"  - semantic_discovery ⚡ ({n_discovery}): AI vector expansion (semantically related)",
            "",
            "CRITICAL SOURCE CITATION RULES:",
            "  - Every factual claim MUST cite its source_id WITH the meeting_url as a markdown link.",
            "  - FORMAT: [source_XXXXXXXX](/meetings?uid=UID)",
            "  - Example: \"电动化市占率从15%提升至22%（[source_b0620259](/meetings?uid=b0620259-4858-4785-97c7-7e882a4449dc)）\"",
            "  - Each record below has a 'Meeting URL' line — parse the UID from it for your citation.",
            "  - DO NOT use plain numbers like [1] or [5] — use the actual source_id with its link.",
            "",
        ]
        for i, r in enumerate(results, 1):
            badge = "⚡" if r.match_type == "semantic_discovery" else " "
            lines.append(f"[{badge} Result {i}] ({r.match_type})")
            lines.append(f"  Source ID: {r.source_id}")
            if r.meeting_url:
                lines.append(f"  Meeting URL: {r.meeting_url}  ← USE THIS for citations: [{r.source_id}]({r.meeting_url})")
            lines.append(f"  Company: {r.company}")
            lines.append(f"  Date: {r.meeting_date}")
            lines.append(f"  Source: {r.source_tag}")
            if r.file_name:
                lines.append(f"  File: {r.file_name}")
            if r.industry:
                lines.append(f"  Industry: {r.industry}")
            if r.sentiment_val is not None:
                lines.append(f"  Sentiment: {r.sentiment_val:+d}")
            if r.keywords_clean:
                lines.append(f"  Keywords: {r.keywords_clean}")
            if r.mentioned_companies and mode == "full_doc":
                lines.append(f"  Mentioned Companies: {r.mentioned_companies}")
            if r.core_summary:
                lines.append(f"  Summary: {r.core_summary}")
            if r.key_points:
                lines.append(f"  Key Points: {r.key_points}")
            if mode in ("deep_dive", "full_doc") and r.full_content:
                lines.append(f"  → Full Content ({len(r.full_content)} chars):\n{r.full_content}")
            if mode in ("deep_dive", "full_doc") and r.q_n_a:
                lines.append(f"  → Q&A ({len(r.q_n_a)} chars):\n{r.q_n_a}")
            lines.append(f"  Relevance: {r.combined_score:.3f}")
            if r.match_type == "semantic_discovery":
                lines.append("  ⚠ Note: Semantically related — not keyword-matched. Verify facts independently.")
            lines.append("")

        return "\n".join(lines)
