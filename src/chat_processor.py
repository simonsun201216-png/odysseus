# src/chat_processor.py
import logging
import math
import re
import time
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
from src.chat_helpers import extract_urls
from src.youtube_handler import is_youtube_url
from src.search import comprehensive_web_search, fetch_webpage_content
from src.prompt_security import UNTRUSTED_CONTEXT_POLICY, untrusted_context_message

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.data_sync import ProphetisMeetingService
from services.data_sync.kb_client import KnowledgeBaseClient, KBSearchResult

logger = logging.getLogger(__name__)

# ── Stopwords & tokenizer ──

_STOPWORDS = frozenset(
    "a an the is am are was were be been being have has had do does did "
    "will would shall should can could may might must need ought dare "
    "i me my mine we us our ours you your yours he him his she her hers "
    "it its they them their theirs this that these those "
    "and but or nor not no so if then else than too also very "
    "in on at to for of by with from up out about into over after "
    "what when where which who whom how why all each every some any "
    "just very really actually like well also still already even "
    "oh ok okay yes yeah hey hi hello thanks thank please sorry "
    "much more most own other another such only same here there "
    "because while during before until since through between both "
    "few many several some none nothing something anything everything "
    "get got make made go going went been come came take took "
    "know think want let say tell give see look find way thing "
    "don doesn didn won wouldn couldn shouldn wasn weren isn aren haven hasn "
    "don't doesn't didn't won't wouldn't couldn't shouldn't "
    "it's i'm i've i'll i'd you're you've you'll he's she's we're we've they're they've "
    "that's there's here's what's who's how's let's can't".split()
)

def _content_tokens(text: str) -> list:
    """Extract meaningful content words: no stopwords, min 3 chars, lowercase."""
    words = re.findall(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', text.lower())
    return [w for w in words if len(w) >= 3 and w not in _STOPWORDS]


class ChatProcessor:
    def __init__(self, memory_manager, personal_docs_manager, memory_vector=None, skills_manager=None, prophetis_meetings=None, kb_client=None):
        self.memory_manager = memory_manager
        self.personal_docs_manager = personal_docs_manager
        self.memory_vector = memory_vector
        self.skills_manager = skills_manager
        self.prophetis_meetings = prophetis_meetings
        self.kb_client = kb_client

    # Minimum similarity score for RAG results to be injected
    RAG_SIMILARITY_THRESHOLD = 0.35

    def _hybrid_retrieve(self, message: str, mem_entries: list, k: int = 5) -> list:
        """Retrieve memories relevant to the message.

        Uses BM25-style keyword scoring + optional vector similarity.
        Recency is a tiebreaker only, never the primary signal.
        """
        if not mem_entries or not message.strip():
            return []

        now = time.time()
        query_tokens = _content_tokens(message)

        # If the query has no meaningful tokens, skip keyword retrieval entirely
        if not query_tokens:
            # Fall back to vector-only if available
            if not (self.memory_vector and self.memory_vector.healthy):
                return []

        # ── Build IDF from the memory corpus ──
        N = len(mem_entries)
        doc_freq = Counter()  # token -> how many memories contain it
        mem_token_cache = {}  # mem_id -> set of content tokens
        for mem in mem_entries:
            toks = set(_content_tokens(mem["text"]))
            mem_token_cache[mem["id"]] = toks
            for t in toks:
                doc_freq[t] += 1

        def _bm25_score(query_toks, mem_id):
            """BM25-inspired score between query and a memory."""
            mem_toks = mem_token_cache.get(mem_id, set())
            if not mem_toks or not query_toks:
                return 0.0
            score = 0.0
            mem_len = len(mem_toks)
            avg_len = max(sum(len(v) for v in mem_token_cache.values()) / N, 1)
            k1, b = 1.5, 0.75
            for qt in query_toks:
                if qt not in mem_toks:
                    continue
                df = doc_freq.get(qt, 0)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                tf = 1  # binary presence (memory entries are short)
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * mem_len / avg_len))
                score += idf * tf_norm
            return score

        # ── Score all candidates ──
        has_vector = self.memory_vector and self.memory_vector.healthy
        vector_scores = {}

        if has_vector:
            results = self.memory_vector.search(message, k=min(k * 3, 20))
            mem_by_id = {m["id"]: m for m in mem_entries}
            for r in results:
                if r["memory_id"] in mem_by_id:
                    vector_scores[r["memory_id"]] = max(r["score"], 0.0)

        scored = []
        for mem in mem_entries:
            mid = mem["id"]
            vs = vector_scores.get(mid, 0.0)
            kw = _bm25_score(query_tokens, mid)

            # Normalize BM25 to roughly 0-1 range (cap at a reasonable max)
            kw_norm = min(kw / 6.0, 1.0) if kw > 0 else 0.0

            # Category-aware boost for identity/contact queries
            category = mem.get("category", "fact")
            msg_lower = message.lower()
            mem_lower = mem["text"].lower()
            cat_boost = 1.0
            if any(w in msg_lower for w in ["name", "who am i", "my name"]):
                if category == "identity" or any(w in mem_lower for w in ["name is", "i am", "called"]):
                    cat_boost = 1.4
            elif any(w in msg_lower for w in ["phone", "email", "address", "contact"]):
                if category == "contact" or "@" in mem_lower:
                    cat_boost = 1.3
            elif any(w in msg_lower for w in ["like", "prefer", "favorite"]):
                if category == "preference":
                    cat_boost = 1.2

            kw_norm = min(kw_norm * cat_boost, 1.0)

            # Recency — tiebreaker only (max 5% contribution)
            ts = mem.get("timestamp", 0)
            days_old = max((now - ts) / 86400, 0)
            recency = 1.0 / (1.0 + days_old * 0.05)

            # Gate: need real relevance, not just recency
            if has_vector:
                if vs < 0.20 and kw_norm < 0.08:
                    continue
                final = (0.55 * vs) + (0.40 * kw_norm) + (0.05 * recency)
            else:
                if kw_norm < 0.08:
                    continue
                final = (0.95 * kw_norm) + (0.05 * recency)

            if final > 0.12:
                scored.append((final, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:k]]

    async def build_context_preface(
        self,
        message: str,
        session: Any,
        use_web: bool = False,
        use_rag: bool = True,
        use_memory: bool = True,
        time_filter: Optional[str] = None,
        preset_system_prompt: Optional[str] = None,
        owner: Optional[str] = None,
        character_name: Optional[str] = None,
        agent_mode: bool = False,
        incognito: bool = False,
        use_skills: bool = True,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]], List[Dict[str, str]]]:
        """Build the context preface for LLM calls.

        Returns:
            Tuple of (preface messages, rag_sources list)
        """
        preface = []
        rag_sources = []

        # Add preset system prompt if specified
        if preset_system_prompt:
            preface.append({
                "role": "system",
                "content": preset_system_prompt
            })
        if not agent_mode:
            try:
                from src.user_time import current_datetime_prompt
                preface.append({
                    "role": "system",
                    "content": current_datetime_prompt(),
                })
            except Exception:
                logger.debug("Failed to add current date/time context", exc_info=True)
        preface.append({
            "role": "system",
            "content": UNTRUSTED_CONTEXT_POLICY,
        })

        # Prophetis meeting intelligence: announce capability to the model so it
        # knows that relevant meeting records are automatically injected below.
        # IMPORTANT: This MUST stay BEFORE web search in the prompt so the model
        # sees the priority rule before any conflicting web results.
        if use_rag and (self.prophetis_meetings or self.kb_client):
            logger.info("ProphetisMeetingService is available, adding capability announcement")
            preface.append({
                "role": "system",
                "content": (
                    "When the user asks about a specific company, industry, market trend, "
                    "investment research, or meeting-related topics, relevant meeting records "
                    "are automatically retrieved from this database and injected below under "
                    "'meeting intelligence'. Each record includes the company name, date, "
                    "industry, source type (e.g. field research, earnings call, expert call), "
                    "sentiment, keywords, summary, and key points.\n\n"
                    "IMPORTANT — PRIORITY RULES (ABSOLUTE):\n"
                    "1. The Prophetis meeting database is your PRIMARY and most authoritative source. "
                    "It contains proprietary expert analysis that external web sources cannot provide.\n"
                    "2. ALWAYS cite meeting data FIRST in your response. Reference the Source ID, "
                    "company name, and meeting date explicitly.\n"
                    "3. Web search results (if provided) are SUPPLEMENTARY ONLY. Use them solely to "
                    "fill gaps the meeting data does not cover, or to update time-sensitive numbers. "
                    "Never replace meeting data with web data when the meeting database covers the topic.\n"
                    "4. When the user specifically asks about their database or meeting records, "
                    "respond using meeting data FIRST and foremost.\n\n"
                    "RESEARCH WORKFLOW:\n"
                    "- You have access to PROPRIETARY MEETING DATA (injected below under 'meeting intelligence').\n"
                    "- You also have access to WEB SEARCH RESULTS (injected below under 'web search results').\n"
                    "- Your task is to SYNTHESIZE all these data sources into a comprehensive analysis.\n"
                    "- As the hedge fund research team lead, you represent the collective expertise of your team.\n"
                    "- Structure your response with clear sections: thesis, evidence from meetings, market context from web, risks, and actionable conclusions.\n"
                    "\n"
                    "CRITICAL — MEETING_URL CITATION RULES:\n"
                    "- Every meeting record below has a Meeting URL field. You MUST use it.\n"
                    "- Format EVERY citation as a markdown link: [source_XXXXXXXX](/meetings?uid=XXXX...)\n"
                    "- Example: \"电动化市占率从15%提升至22%（[source_b0620259](/meetings?uid=b0620259-...)）\"\n"
                    "- The /meetings?uid= link opens the full original meeting record in a new tab.\n"
                    "- NEVER use plain [N] or [source_id] without a clickable link.\n"
                    "- If a claim synthesizes multiple records, cite ALL relevant source_ids with their links.\n"
                    "- Uncited claims will be treated as unsupported speculation.\n"
                    "- Note: semantic_discovery ⚡ results are AI-expanded; verify facts independently."
                ),
            })

        # Memory: pinned (always included) + extended (RAG-retrieved when relevant)
        self._last_used_memories = []  # track what was injected
        if use_memory:
            mem_entries = self.memory_manager.load(owner=owner)

            pinned = [m for m in mem_entries if m.get("pinned")]
            extended = [m for m in mem_entries if not m.get("pinned")]

            _used_ids: list = []
            if pinned:
                pinned_text = "\n- ".join([m["text"] for m in pinned])
                preface.append(untrusted_context_message(
                    "saved memory: pinned user facts",
                    f"Core facts about the user:\n- {pinned_text}",
                ))
                for m in pinned:
                    self._last_used_memories.append({"text": m["text"], "category": m.get("category", "fact"), "type": "pinned"})
                    if m.get("id"):
                        _used_ids.append(m["id"])

            if extended:
                relevant = self._hybrid_retrieve(message, extended, k=3)
                if relevant:
                    ext_text = "\n".join([f"- {m['text']}" for m in relevant])
                    preface.append(untrusted_context_message(
                        "saved memory: retrieved context",
                        (
                            "Memory context. Do not reference unless the user asks "
                            f"about these topics.\n{ext_text}"
                        ),
                    ))
                    for m in relevant:
                        self._last_used_memories.append({"text": m["text"], "category": m.get("category", "fact"), "type": "recalled"})
                        if m.get("id"):
                            _used_ids.append(m["id"])

            # Bump usage counters for the memories that were actually injected.
            if _used_ids and hasattr(self.memory_manager, "increment_uses"):
                try:
                    self.memory_manager.increment_uses(_used_ids)
                except Exception as _e:
                    logger.warning("Failed to increment memory uses: %s", _e)

            # (skills index injection moved out — see below; only fires in
            # agent mode so chat mode and incognito stay clean.)

        # RAG: search if enabled and rag_manager available, inject only above threshold
        if use_rag:
            try:
                rag_manager = getattr(self.personal_docs_manager, 'rag_manager', None)
                if rag_manager:
                    results = rag_manager.search(message, k=5, owner=owner)
                    # Filter by similarity threshold
                    relevant = [r for r in results if r.get("similarity", 0) >= self.RAG_SIMILARITY_THRESHOLD]
                    if relevant:
                        logger.info(f"RAG: {len(relevant)}/{len(results)} results above threshold {self.RAG_SIMILARITY_THRESHOLD}")
                        rag_sources = [
                            {
                                "filename": r["metadata"].get("filename", r["metadata"].get("source", "unknown")),
                                "snippet": r["document"][:200],
                                "similarity": round(r.get("similarity", 0), 3)
                            }
                            for r in relevant
                        ]
                        rag_content = "Relevant documents:\n\n" + "\n\n---\n\n".join(
                            f"[{s['filename']}]\n{r['document']}" for s, r in zip(rag_sources, relevant)
                        )
                        if len(rag_content) > 10000:
                            rag_content = rag_content[:10000] + "\n[Truncated]"
                        preface.append(untrusted_context_message("retrieved documents", rag_content))
            except Exception as e:
                logger.warning(f"RAG retrieval failed: {e}")

        # Add web search if enabled (BEFORE meeting intelligence, so meeting data
        # is closer to the user message and gets more model attention)
        web_sources = []
        if use_web:
            try:
                web_context, web_sources = comprehensive_web_search(
                    message, time_filter=time_filter, return_sources=True
                )
                # When meeting intelligence is also available, tag web results as auxiliary
                # so the model doesn't favor external web sources over proprietary data.
                if self.prophetis_meetings:
                    web_context = (
                        "═══════════════════════════════════════════════\n"
                        "NOTE: These web search results are EXTERNAL sources. They are provided "
                        "for supplementary reference ONLY. The proprietary Prophetis meeting "
                        "database (listed below under 'meeting intelligence') takes priority "
                        "as your PRIMARY source — it contains expert financial analysis that "
                        "web sources cannot match. Web data may be incomplete or outdated.\n"
                        "═══════════════════════════════════════════════\n\n"
                        + web_context
                    )
                preface.append(untrusted_context_message("web search results", web_context))
            except Exception as e:
                logger.error(f"Web search failed: {e}")
                preface.append({"role": "system", "content": "Web search encountered an error and could not retrieve results."})

        # Prophetis Knowledge Base: structured hybrid search with source_id tracking.
        # Uses the optimized kb.search_meetings_v2 (0.05s avg) via the KnowledgeBaseClient.
        # Falls back to legacy ProphetisMeetingService if KB client is unavailable.
        logger.info("Meeting intelligence check: use_rag=%s kb_client=%s prophetis=%s",
                     use_rag, bool(self.kb_client), bool(self.prophetis_meetings))
        if use_rag and (self.kb_client or self.prophetis_meetings):
            results: list = []
            try:
                logger.info("Knowledge Base search starting for: %.80s", message)
                if self.kb_client:
                    # Deep research keywords trigger multi-angle search
                    _research_kw = [
                        "投研", "做多", "做空", "深入", "研究", "分析",
                        "research", "analysis", "deep dive", "opportunity",
                        "invest", "trade", "long", "short", "fund",
                    ]
                    _is_deep = any(kw in message.lower() for kw in _research_kw)
                    if _is_deep:
                        logger.info("Deep research query detected — using deep_search")
                        results = await self.kb_client.deep_search(
                            query=message,
                            mode="full_doc",
                            k=30,
                            min_score=0.0,
                        )
                    else:
                        results = await self.kb_client.search(
                            query=message,
                            mode="full_doc",
                            k=8,
                            min_score=0.0,
                        )
                elif self.prophetis_meetings:
                    # Legacy fallback
                    import asyncio
                    loop = asyncio.get_event_loop()
                    results = await loop.run_in_executor(
                        None, self.prophetis_meetings.search_sync, message, 5
                    )
                logger.info(
                    "Knowledge Base search returned %d results for: %.80s",
                    len(results) if results else 0, message,
                )
                if results:
                    if self.kb_client:
                        meeting_context = self.kb_client.format_for_context(results, mode="full_doc")
                    else:
                        meeting_context = self.prophetis_meetings.format_context(results)
                    if len(meeting_context) > 12000:
                        meeting_context = meeting_context[:12000] + "\n[Truncated]"
                    logger.info("Knowledge Base injection: %d chars", len(meeting_context))
                    preface.append(untrusted_context_message("meeting intelligence", meeting_context))
                    rag_sources.extend([
                        {
                            "filename": f"{r.company} ({r.meeting_date})" if hasattr(r, 'company') and r.company
                                       else f"{getattr(r, 'main_company', '?')} ({r.meeting_date})",
                            "snippet": (r.core_summary or r.summary or "")[:150],
                            "similarity": round(r.combined_score, 3) if r.combined_score else 0.0,
                        }
                        for r in results
                    ])
                else:
                    logger.info("Knowledge Base search returned 0 results — no injection")
            except Exception as e:
                logger.warning("Knowledge Base search failed: %s", e)

            # ── Recent meetings overview ──
            # Always inject the most recent N meetings so the model can answer
            # blanket date-range queries like "summarise last 3 days".
            try:
                recent_uids = {r.uid for r in results} if results else set()
                recent_records: list = []
                if self.kb_client:
                    recent = await self.kb_client.search(
                        query="", mode="full_doc", k=15, min_score=0.0,
                    )
                    recent_records = recent
                elif self.prophetis_meetings:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    recent = await loop.run_in_executor(
                        None, self.prophetis_meetings.get_recent_meetings, 10
                    )
                    recent_records = recent
                # Deduplicate against query results
                fresh = [r for r in recent_records if r.uid not in recent_uids]
                if fresh:
                    lines = [
                        "--- Recent Meetings Overview ---",
                        "The most recent meeting records in the Prophetis database "
                        "(may overlap with the query search above):",
                    ]
                    for i, r in enumerate(fresh, 1):
                        summary = (r.core_summary or "")[:180]
                        company = r.company if hasattr(r, 'company') and r.company else r.main_company
                        source_tag = r.source_tag if hasattr(r, 'source_tag') else getattr(r, 'source', '?')
                        mu = r.meeting_url if hasattr(r, 'meeting_url') and r.meeting_url else ""
                        sid = r.source_id if hasattr(r, 'source_id') and r.source_id else ""
                        link = f" → [{sid}]({mu})" if mu and sid else ""
                        lines.append(
                            f"  [{i}] {company} ({r.meeting_date})"
                            f" [{source_tag}] — {summary}{link}"
                        )
                    recent_context = "\n".join(lines)
                    logger.info(
                        "Recent meetings injection: %d records, %d chars",
                        len(fresh), len(recent_context),
                    )
                    preface.append(untrusted_context_message(
                        "recent meetings overview", recent_context,
                    ))
                    rag_sources.extend([
                        {
                            "filename": f"{r.company if hasattr(r, 'company') and r.company else r.main_company} ({r.meeting_date})",
                            "snippet": (r.core_summary or "")[:150],
                            "similarity": 0.0,
                        }
                        for r in fresh
                    ])
            except Exception as e:
                logger.warning("Recent meetings overview failed: %s", e)

        # Process non-YouTube URLs in message (YouTube handled by preprocess_message)
        # Skip auto-fetch for long pastes (the user already pasted the content —
        # fetching every embedded link buries the actual question under
        # hundreds of KB of duplicate page HTML and confuses the model) or for
        # link-heavy pastes (>3 URLs typically means it's a boilerplate-laden
        # blog post, not a "summarize this URL" request).
        urls = extract_urls(message)
        non_yt_urls = [u for u in urls if not is_youtube_url(u)]
        skip_url_fetch = len(message) > 2000 or len(non_yt_urls) > 3
        if not skip_url_fetch:
            for url in non_yt_urls:
                result = fetch_webpage_content(url)
                if result.get('success'):
                    content = result.get('content', '')[:10000]
                    preface.append(untrusted_context_message(
                        f"web page: {url}",
                        f"Content from {url}:\n\n{content}",
                    ))

        # Skills index — progressive disclosure. Only injected when the
        # model has the `manage_skills` tool available (agent_mode), and
        # never in incognito mode (the user has explicitly opted out of
        # context retention this turn). In plain chat mode the model can't
        # call the tool anyway, so the index would be noise.
        if agent_mode and not incognito and use_skills and self.skills_manager:
            try:
                idx = self.skills_manager.index_for(owner=owner)
            except Exception as e:
                logger.debug(f"Skills index unavailable: {e}")
                idx = []
            if idx:
                by_cat: Dict[str, list] = {}
                for s in idx:
                    by_cat.setdefault(s.get("category") or "general", []).append(s)
                lines = ["[Available skills — call manage_skills(action='view', name='...') to load one when relevant]"]
                for cat in sorted(by_cat):
                    lines.append(f"  {cat}:")
                    for s in sorted(by_cat[cat], key=lambda x: x["name"]):
                        desc = s.get("description") or ""
                        lines.append(f"    - {s['name']}: {desc}" if desc else f"    - {s['name']}")
                preface.append(untrusted_context_message("available skills index", "\n".join(lines)))

        return preface, rag_sources, web_sources
