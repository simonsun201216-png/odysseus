"""
routes/kb_routes.py

Knowledge Base API routes — structured query, timeline, source traceback.

Endpoints:
  POST /api/kb/query       — Structured hybrid search
  POST /api/kb/timeline    — Time-series aggregation
  GET  /api/kb/source/{id} — Source traceability (raw record)
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


def setup_kb_routes(kb_client) -> APIRouter:
    """Register KB API routes. kb_client is a KnowledgeBaseClient instance."""
    router = APIRouter(tags=["kb"])

    @router.post("/api/kb/query")
    async def kb_query(body: dict[str, Any]):
        """Structured hybrid search against the knowledge base.

        Request body:
        {
            "query": "自然语言查询",
            "companies": ["三一重工"],
            "industries": ["工业制造业"],
            "keywords": ["电动化"],
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
            "source_tags": ["3B", "COMIN"],
            "mode": "scan",           # "scan" | "deep_dive"
            "k": 10,
            "min_score": 0.0
        }

        Returns:
        {
            "total": 42,
            "results": [
                {
                    "source_id": "source_b0620259",
                    "uid": "b0620259-...",
                    "company": "三一重工",
                    "meeting_date": "2025-06-15",
                    "industry": "工业制造业",
                    "source_tag": "3B",
                    "sentiment_val": 2,
                    "keywords_clean": "电动化, 出口, ...",
                    "summary": "...",
                    "key_points": "...",
                    "full_content": "...",     // only in deep_dive mode
                    "q_n_a": "...",             // only in deep_dive mode
                    "relevance": 0.87
                }
            ]
        }
        """
        query = body.get("query", "")
        mode = body.get("mode", "scan")
        k = body.get("k", 10)
        min_score = body.get("min_score", 0.0)

        if not query and not body.get("companies") and not body.get("industries") and not body.get("keywords"):
            raise HTTPException(
                status_code=400,
                detail="At least one of query, companies, industries, or keywords is required",
            )

        try:
            # Use search_with_complement for hybrid FTS + vector complement detection
            results = await kb_client.search_with_complement(
                query=query,
                companies=body.get("companies"),
                industries=body.get("industries"),
                keywords=body.get("keywords"),
                source_tags=body.get("source_tags"),
                date_from=body.get("date_from"),
                date_to=body.get("date_to"),
                mode=mode,
                k=k,
                min_score=min_score,
            )
        except Exception as e:
            logger.error("KB query failed: %s", e)
            raise HTTPException(status_code=502, detail=f"KB search failed: {e}")

        serialized = [
            {
                "source_id": r.source_id,
                "uid": r.uid,
                "company": r.company,
                "meeting_date": r.meeting_date,
                "industry": r.industry,
                "source_tag": r.source_tag,
                "sentiment_val": r.sentiment_val,
                "keywords_clean": r.keywords_clean,
                "summary": r.core_summary,
                "key_points": r.key_points,
                "full_content": r.full_content if mode in ("deep_dive", "full_doc") else None,
                "q_n_a": r.q_n_a if mode in ("deep_dive", "full_doc") else None,
                "relevance": round(r.combined_score, 4),
                "match_type": r.match_type,
                "file_name": r.file_name if mode == "full_doc" else None,
                "mentioned_companies": r.mentioned_companies if mode == "full_doc" else None,
                "meeting_url": r.meeting_url,
            }
            for r in results
        ]

        return {
            "total": len(serialized),
            "results": serialized,
        }

    @router.post("/api/kb/timeline")
    async def kb_timeline(body: dict[str, Any]):
        """Time-series aggregation for a company or keyword.

        Request body:
        {
            "company": "三一重工",     // optional
            "keyword": "电动化",       // optional
            "date_from": "2024-01-01",
            "date_to": "2026-06-01",
            "interval": "quarter"     // "month" | "quarter"
        }

        Returns:
        {
            "timeline": [
                {
                    "period": "2025-Q2",
                    "meeting_count": 12,
                    "avg_sentiment": 1.5,
                    "top_keywords": [["电动化", 8], ...],
                    "companies": ["三一重工"]
                }
            ]
        }
        """
        try:
            timeline_data = await kb_client.timeline(
                company=body.get("company"),
                keyword=body.get("keyword"),
                date_from=body.get("date_from"),
                date_to=body.get("date_to"),
                interval=body.get("interval", "month"),
            )
        except Exception as e:
            logger.error("KB timeline failed: %s", e)
            raise HTTPException(status_code=502, detail=f"KB timeline failed: {e}")

        return {"timeline": timeline_data}

    @router.get("/api/kb/source/{source_id}")
    async def kb_source_lookup(source_id: str):
        """Trace back from source_id to the full raw meeting record.

        Returns the complete public.meetings row for the given source_id.
        Used for verification and audit of LLM citations.
        """
        if not source_id.startswith("source_"):
            raise HTTPException(
                status_code=400,
                detail="Invalid source_id format. Expected: source_XXXXXXXX",
            )

        try:
            record = await kb_client.lookup_by_source_id(source_id)
        except Exception as e:
            logger.error("KB source lookup failed: %s", e)
            raise HTTPException(status_code=502, detail=f"Source lookup failed: {e}")

        if not record:
            raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

        return record

    return router
