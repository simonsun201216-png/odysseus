"""
crew_orchestrator.py — Hedge fund team analysis API.

POST /api/crew/hedge-fund/run   — start a team analysis
GET  /api/crew/hedge-fund/status/{analysis_id} — check results
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.database import SessionLocal, CrewMember
from src.auth_helpers import get_current_user

logger = logging.getLogger(__name__)

# In-memory store for active/completed analyses.
# In production this should move to the DB, but for v1 this is fine.
_analyses: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class HedgeFundRunRequest(BaseModel):
    query: str
    language: Optional[str] = None
    model: Optional[str] = None
    endpoint_url: Optional[str] = None
    max_iterations: int = 3


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def setup_crew_orchestrator_routes() -> APIRouter:
    router = APIRouter(prefix="/api/crew/hedge-fund", tags=["hedge-fund"])

    def _owner(request: Request) -> str:
        owner = get_current_user(request)
        if not owner:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return owner

    @router.post("/run")
    async def run_team_analysis(payload: HedgeFundRunRequest, request: Request):
        """Start a hedge fund team analysis. Runs synchronously and returns results."""
        owner = _owner(request)

        # Resolve model/endpoint from the user's default assistant if not specified
        model = payload.model
        endpoint_url = payload.endpoint_url
        if not model or not endpoint_url:
            db = SessionLocal()
            try:
                assistant = db.query(CrewMember).filter(
                    CrewMember.owner == owner,
                    CrewMember.is_default_assistant == True,  # noqa: E712
                ).first()
                if assistant:
                    if not model:
                        model = assistant.model
                    if not endpoint_url:
                        endpoint_url = assistant.endpoint_url
            finally:
                db.close()

        if not model or not endpoint_url:
            raise HTTPException(
                status_code=400,
                detail="No model/endpoint configured. Set up a model in Settings or specify model/endpoint_url.",
            )

        analysis_id = str(uuid.uuid4())[:12]
        logger.info(f"[crew_orchestrator] Starting analysis {analysis_id} for {owner}: {payload.query[:80]}...")

        from src.orchestrator import run_team_analysis as _run_team

        try:
            state = await _run_team(
                query=payload.query,
                owner=owner,
                endpoint_url=endpoint_url,
                model=model,
                analysis_id=analysis_id,
                language=payload.language,
                max_iterations=payload.max_iterations,
            )
        except Exception as e:
            logger.exception(f"[crew_orchestrator] Analysis {analysis_id} failed")
            raise HTTPException(status_code=500, detail=str(e))

        # Build response
        result = {
            "analysis_id": analysis_id,
            "query": state.query,
            "language": state.language,
            "iterations": state.iteration,
            "final_answer": state.final_answer,
            "reports": {
                sid: {
                    "name": _get_specialist_name(sid),
                    "summary": state.summaries.get(sid, ""),
                    "full_length": len(state.reports.get(sid, "")),
                }
                for sid in state.reports
            },
            "report_count": len(state.reports),
            "completed_at": datetime.utcnow().isoformat() + "Z",
        }

        # Cache in memory for status checks
        _analyses[analysis_id] = result

        return result

    @router.get("/status/{analysis_id}")
    async def get_analysis_status(analysis_id: str, request: Request):
        """Check the status/results of a completed analysis."""
        owner = _owner(request)
        result = _analyses.get(analysis_id)
        if not result:
            raise HTTPException(status_code=404, detail="Analysis not found")
        return result

    @router.get("/specialists")
    async def list_specialists():
        """Return the specialist roster available for team analyses."""
        from src.orchestrator import SPECIALIST_DEFS
        return {
            "specialists": [
                {
                    "id": sid,
                    "name": spec["name"],
                    "role": spec["role"],
                    "specialty": spec["specialty"],
                    "priority": spec["priority"],
                }
                for sid, spec in SPECIALIST_DEFS.items()
            ]
        }

    return router


def _get_specialist_name(specialist_id: str) -> str:
    from src.orchestrator import SPECIALIST_DEFS
    spec = SPECIALIST_DEFS.get(specialist_id)
    return spec["name"] if spec else specialist_id
