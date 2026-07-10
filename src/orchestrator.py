"""
orchestrator.py — Multi-agent team orchestration engine.

Implements the "Hedge Fund" research team pattern from prophetis-ai:
  Stanley (CIO) → dynamic task decomposition → parallel specialists → synthesis

Reuses Odysseus's existing stream_agent_loop for individual specialist execution
and direct LLM calls for structured routing decisions.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HedgeFundState:
    """Mutable state for a single team analysis run."""
    query: str
    messages: list = field(default_factory=list)
    reports: dict = field(default_factory=dict)       # specialist_id → full text
    summaries: dict = field(default_factory=dict)      # specialist_id → compressed
    next_agents: list = field(default_factory=list)
    iteration: int = 0
    final_answer: str = ""
    language: str = "English"
    task_plan: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Specialist definitions — the "crew" roster
# ---------------------------------------------------------------------------

SPECIALIST_DEFS = {
    # ── P0: Core analysts (each gets a full CrewMember + agent loop) ──
    "jintao": {
        "id": "jintao",
        "name": "Jintao",
        "role": "China A+H Chief Strategist",
        "specialty": "China markets, cycle theory, A-share, H-share, macro policy",
        "priority": "P0",
        "temperature": 0.35,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search", "financial_search",
                          "openbb_macro", "openbb_fetcher", "yahoo_finance", "read_filings"],
    },
    "fundamental": {
        "id": "fundamental",
        "name": "Fundamental Analyst",
        "role": "Fundamental Analyst",
        "specialty": "Financial statements, DCF, DuPont, ROIC/WACC, valuation",
        "priority": "P0",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "financial_search", "financial_metrics",
                          "read_filings", "advanced_search", "openbb_fetcher"],
    },
    "technician": {
        "id": "technician",
        "name": "Technical Analyst",
        "role": "Technical Analyst",
        "specialty": "Market timing, trend exhaustion, Elliott Wave, relative strength",
        "priority": "P0",
        "temperature": 0.4,
        "enabled_tools": ["web_search", "web_fetch", "financial_search", "yahoo_finance",
                          "openbb_fetcher", "advanced_search"],
    },
    "riskmaster": {
        "id": "riskmaster",
        "name": "Risk Manager",
        "role": "Risk Manager",
        "specialty": "VaR, stress tests, position sizing, correlation, downside protection",
        "priority": "P0",
        "temperature": 0.2,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search",
                          "financial_metrics", "read_filings"],
    },
    # ── P1: Strategy (used via call_specialist tool) ──
    "jessie": {
        "id": "jessie",
        "name": "Jessie",
        "role": "Portfolio Strategist",
        "specialty": "Portfolio construction, capital allocation, factor rotation",
        "priority": "P1",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "financial_metrics", "openbb_fetcher"],
    },
    "elliott": {
        "id": "elliott",
        "name": "Elliott",
        "role": "Macro Strategist",
        "specialty": "Global macro, FX, rates, commodities, central bank policy",
        "priority": "P1",
        "temperature": 0.35,
        "enabled_tools": ["web_search", "web_fetch", "openbb_macro", "financial_search"],
    },
    "theo": {
        "id": "theo",
        "name": "Theo",
        "role": "Event-Driven Strategist",
        "specialty": "M&A, activist investing, special situations, catalyst analysis",
        "priority": "P1",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search", "read_filings"],
    },
    # ── P2: Industry (used via call_specialist tool) ──
    "stella": {
        "id": "stella",
        "name": "Stella",
        "role": "Semiconductor Analyst",
        "specialty": "Semiconductors, chip design, fab capacity, supply chain",
        "priority": "P2",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search", "financial_search"],
    },
    "vogue": {
        "id": "vogue",
        "name": "Vogue",
        "role": "AI/Software Analyst",
        "specialty": "AI/ML, SaaS, cloud, enterprise software, developer tools",
        "priority": "P2",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search", "financial_search"],
    },
    "lily": {
        "id": "lily",
        "name": "Lily",
        "role": "Consumer Analyst",
        "specialty": "Consumer brands, retail, e-commerce, discretionary spending",
        "priority": "P2",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search", "financial_metrics"],
    },
    "rose": {
        "id": "rose",
        "name": "Rose",
        "role": "Healthcare/Biotech Analyst",
        "specialty": "Pharma, biotech, medical devices, healthcare policy",
        "priority": "P2",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search", "read_filings"],
    },
    "spark": {
        "id": "spark",
        "name": "Spark",
        "role": "EV/Energy Analyst",
        "specialty": "Electric vehicles, batteries, renewable energy, commodities",
        "priority": "P2",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search", "openbb_fetcher"],
    },
    "rex": {
        "id": "rex",
        "name": "Rex",
        "role": "Financials/Fintech Analyst",
        "specialty": "Banks, insurance, fintech, payments, crypto/blockchain",
        "priority": "P2",
        "temperature": 0.3,
        "enabled_tools": ["web_search", "web_fetch", "advanced_search", "financial_metrics"],
    },
}

P0_IDS = {k for k, v in SPECIALIST_DEFS.items() if v["priority"] == "P0"}
P1_IDS = {k for k, v in SPECIALIST_DEFS.items() if v["priority"] == "P1"}
P2_IDS = {k for k, v in SPECIALIST_DEFS.items() if v["priority"] == "P2"}


# ---------------------------------------------------------------------------
# System prompts (translated from prophetis-ai TypeScript sources)
# ---------------------------------------------------------------------------

STANLEY_SYSTEM_PROMPT = """\
You are **Stanley**, the Chief Investment Officer (CIO) of a top-tier hedge fund.
Your goal is to orchestrate a team of elite analysts to answer the user's query.

**Your Team (Specialist Agents):**
{team_roster}

**Current Status:**
Iteration: {iteration}
Reports Received: {reports_received}
Target Language: {language} (MANDATORY)

**Summary of Findings so far:**
{summaries}

**Orchestration Logic (MANDATORY):**
1. **Dynamic Task Decomposition**: Break the query into a structured research plan. Decide who needs to do what and in what order.
2. **Industry Expertise First**: If the query is about a specific sector (semiconductors, AI, EVs, etc.), call the corresponding industry analyst via `call_specialist`. Do NOT use 'fundamental' for sector-specific deep dives unless no industry specialist exists.
3. **Multi-Sector Companies**: If a company spans multiple industries, call analysts from ALL relevant sectors.
4. **Core Team Support**:
   - Valuation/Financials → 'fundamental'
   - Timing/Charts → 'technician'
   - China/A-share/H-share → 'jintao'
   - Portfolio Risk → 'riskmaster'
   - Strategy/Position Sizing → 'jessie'
   - Macro → 'elliott'
   - Event-Driven → 'theo'
5. **Parallel Execution**: You can call multiple agents in the same round by listing them in 'next_agents'.
6. **Debate & Adjudication**: If reports conflict, call 'riskmaster' or a strategist to adjudicate.
7. **Finalization**: Only return an empty 'next_agents' array when you have a comprehensive, multi-perspective answer.
8. **Language Consistency**: Output ALL instructions and synthesis in {language}.

**Output Format (JSON only — no markdown, no extra text):**
```json
{{
  "next_agents": ["agent_id_1", "agent_id_2"],
  "instructions": "Specific, high-context instructions for the selected agents.",
  "thought": "Your internal reasoning for this scheduling decision.",
  "final_synthesis": "If next_agents is empty, the final executive synthesis."
}}
```
"""

P0_SYSTEM_PROMPTS = {
    "jintao": """\
You are **Jintao**, the China A+H Market Chief Strategist.
Specialty: {specialty}
Task: {instruction}

You are the digital reincarnation of the "Cycle King" (周期天王), applying cycle theory to navigate Chinese and global markets.

**YOUR ANALYSIS FRAMEWORK:**
1. **Cycle Positioning (周期定位)**: Identify the current phase across Kon-Wave, Kuznets, Juglar, and Kitchin cycles.
2. **Policy & Structural Change**: PBoC monetary policy, fiscal stimulus, "New Productive Forces" (新质生产力).
3. **Market Sentiment**: Gauge retail sentiment via social media, capital flows (Northbound, National Team).
4. **Asset Selection**: Focus on AH Premium, high-dividend stability, resource-scarcity sectors.

**MANDATORY:**
- Multi-round search: web_search → advanced_search for deeper context
- Every assertion must have an inline citation [Source Title](URL)
- Include a "Cycle Context" (周期背景) section
- Output strictly in {language}

Your report MUST be thorough, data-driven, and professional.
""",

    "fundamental": """\
You are the **Fundamental Analyst** at the hedge fund.
Specialty: {specialty}
Task: {instruction}

**YOUR ANALYSIS FRAMEWORK (The "4P" for Fundamentals):**
1. **Product**: Category structure, demand durability, penetration, regulatory tailwind/headwind.
2. **Process**: Business model defensibility, value capture, cash flow resilience.
3. **People**: Governance, capital allocation discipline, incentive alignment.
4. **Position**: Market share, scale effects, industry concentration, barriers to entry.

**MANDATORY:**
- Use DCF, relative valuation (PE, PS, EV/EBITDA), ROIC/WACC analysis
- Multi-round search: web_search → financial_search → read_filings
- Every number must be cited: "Revenue grew 15% ([Source](url))"
- Include a **References** section at the end
- Output strictly in {language}

Your report MUST be thorough, data-driven, and professional.
""",

    "technician": """\
You are the **Technical Analyst (Technician)** at the hedge fund.
Specialty: {specialty}
Task: {instruction}

You integrate the frameworks of Laurence Balanco (CLSA), Tom DeMark, and Paul Tudor Jones.

**YOUR ANALYSIS FRAMEWORK:**
1. **Global Context (Balanco)**: Compare to peers, sector, and global indices (Relative Strength).
2. **Trend Exhaustion (DeMark)**: Look for sequential counts (9, 13) to identify trend breaks.
3. **Risk/Reward (Tudor Jones)**: Identify asymmetric 5:1 risk/reward setups.

**MANDATORY:**
- Use yahoo_finance or openbb_fetcher for latest price action
- Include key support/resistance levels and technical indicators
- Inline citations for all price targets and levels
- Output strictly in {language}

Your report MUST be thorough, data-driven, and professional.
""",

    "riskmaster": """\
You are the **Risk Master (Risk Manager)** at the hedge fund.
Specialty: {specialty}
Task: {instruction}

Your job is to be the **Pessimist**. While others look for upside, you look for the cliff.

**YOUR ANALYSIS FRAMEWORK:**
1. **Stress Testing**: What happens if rates rise 1%? What if growth slows? What if geopolitics escalate?
2. **Downside Protection**: Calculate potential drawdowns and tail risks.
3. **Correlation**: Ensure the portfolio isn't secretly betting on the same factor.
4. **Position Sizing**: Recommend sizing based on volatility and conviction.

**MANDATORY:**
- Multi-round search: web_search → advanced_search for regulatory and social risk signals
- Always provide a "Bear Case" scenario with a price target
- Inline citations for all risk factors
- Output strictly in {language}

Your report MUST be thorough, data-driven, and professional.
""",
}


def _build_team_roster() -> str:
    """Build a formatted team roster string for Stanley's prompt."""
    lines = []
    for sid, spec in SPECIALIST_DEFS.items():
        lines.append(f"- {sid}: {spec['name']} ({spec['role']}) — {spec['specialty']} [{spec['priority']}]")
    return "\n".join(lines)


def _get_p0_prompt(specialist_id: str, instruction: str, language: str) -> str:
    """Build the system prompt for a P0 specialist."""
    spec = SPECIALIST_DEFS.get(specialist_id)
    if not spec:
        return instruction
    template = P0_SYSTEM_PROMPTS.get(specialist_id, "{instruction}")
    return template.format(
        specialty=spec["specialty"],
        instruction=instruction,
        language=language,
    )


async def _run_agent_loop(
    endpoint_url: str,
    model: str,
    system_prompt: str,
    user_message: str,
    owner: str,
    session_id: str,
    enabled_tools: list[str],
    max_rounds: int = 15,
    temperature: float = 0.3,
) -> str:
    """Run a single specialist agent through the full agent loop, return text."""
    from src.agent_loop import stream_agent_loop
    from src.llm_core import llm_call_async_with_fallback
    from src.endpoint_resolver import resolve_utility_fallback_candidates

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    # Resolve headers
    headers = {}
    try:
        from core.database import SessionLocal, ModelEndpoint
        from src.endpoint_resolver import normalize_base, build_headers
        db2 = SessionLocal()
        try:
            for ep in db2.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all():
                if normalize_base(ep.base_url) in endpoint_url or endpoint_url in normalize_base(ep.base_url):
                    headers = build_headers(ep.api_key, normalize_base(ep.base_url))
                    break
        finally:
            db2.close()
    except Exception:
        pass

    disabled_tools = set()
    relevant_tools = set(enabled_tools) if enabled_tools else None

    fallbacks = []
    try:
        fallbacks = resolve_utility_fallback_candidates()
    except Exception:
        pass

    full_text = ""
    tool_results = []

    async for event_str in stream_agent_loop(
        endpoint_url=endpoint_url,
        model=model,
        messages=messages,
        max_rounds=max_rounds,
        temperature=temperature,
        session_id=session_id,
        owner=owner,
        headers=headers,
        disabled_tools=disabled_tools,
        relevant_tools=relevant_tools,
        fallbacks=fallbacks,
    ):
        if event_str.startswith("data: ") and not event_str.startswith("data: [DONE]"):
            try:
                data = json.loads(event_str[6:])
                if "delta" in data:
                    full_text += data["delta"]
                elif data.get("type") == "tool_output":
                    summary = data.get("stdout") or data.get("output") or data.get("result") or ""
                    if isinstance(summary, str) and summary.strip():
                        tool_results.append(f"[{data.get('tool', '?')}] {summary[:300]}")
            except (json.JSONDecodeError, KeyError):
                pass

    # Grace summarization if no text was produced
    if not full_text.strip():
        try:
            grace_ctx = "You ran out of steps.\n"
            if tool_results:
                grace_ctx += "Tool results:\n" + "\n".join(tool_results[-3:])
            grace_ctx += "\n\nSummarize what you found. Be concise."
            candidates = [(endpoint_url, model, headers)] + fallbacks
            full_text = await llm_call_async_with_fallback(
                candidates,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": grace_ctx},
                ],
                timeout=30,
            )
            full_text = (full_text or "").strip()
        except Exception as e:
            logger.warning(f"[orchestrator] Grace summarization failed: {e}")
            if tool_results:
                full_text = "\n".join(tool_results[-3:])

    return full_text or "(no output)"


async def _llm_call_structured(
    endpoint_url: str,
    model: str,
    messages: list,
    temperature: float = 0.1,
) -> str:
    """Direct LLM call for structured (JSON) output — used by Stanley."""
    from src.llm_core import llm_call_async_with_fallback
    from src.endpoint_resolver import resolve_utility_fallback_candidates

    headers = {}
    try:
        from core.database import SessionLocal, ModelEndpoint
        from src.endpoint_resolver import normalize_base, build_headers
        db2 = SessionLocal()
        try:
            for ep in db2.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all():
                if normalize_base(ep.base_url) in endpoint_url or endpoint_url in normalize_base(ep.base_url):
                    headers = build_headers(ep.api_key, normalize_base(ep.base_url))
                    break
        finally:
            db2.close()
    except Exception:
        pass

    candidates = [(endpoint_url, model, headers)] + resolve_utility_fallback_candidates()
    text = await llm_call_async_with_fallback(candidates, messages, temperature=temperature, timeout=60)
    return text.strip()


async def _call_specialist_tool(
    specialist_id: str,
    query: str,
    instruction: str,
    language: str,
    endpoint_url: str,
    model: str,
    owner: str,
    analysis_id: str,
) -> str:
    """Run a P1/P2 specialist via agent loop (used as a tool by P0 agents or Stanley)."""
    spec = SPECIALIST_DEFS.get(specialist_id)
    if not spec:
        return f"Unknown specialist: {specialist_id}"

    system_prompt = (
        f"You are {spec['name']} ({spec['role']}) at a hedge fund.\n"
        f"Specialty: {spec['specialty']}\n\n"
        f"Task: {instruction}\n\n"
        f"Use the available tools to research thoroughly. "
        f"Every assertion must have an inline citation. "
        f"Output strictly in {language}.\n\n"
        f"Your report MUST be thorough, data-driven, and professional."
    )

    return await _run_agent_loop(
        endpoint_url=endpoint_url,
        model=model,
        system_prompt=system_prompt,
        user_message=instruction,
        owner=owner,
        session_id=f"{analysis_id}-{specialist_id}",
        enabled_tools=spec["enabled_tools"],
        max_rounds=12,
        temperature=spec["temperature"],
    )


async def _summarize_report(
    specialist_name: str,
    report: str,
    language: str,
    endpoint_url: str,
    model: str,
) -> str:
    """Compress a specialist's full report into a high-fidelity digest for Stanley."""
    from src.llm_core import llm_call_async_with_fallback
    from src.endpoint_resolver import resolve_utility_fallback_candidates

    headers = {}
    try:
        from core.database import SessionLocal, ModelEndpoint
        from src.endpoint_resolver import normalize_base, build_headers
        db2 = SessionLocal()
        try:
            for ep in db2.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all():
                if normalize_base(ep.base_url) in endpoint_url or endpoint_url in normalize_base(ep.base_url):
                    headers = build_headers(ep.api_key, normalize_base(ep.base_url))
                    break
        finally:
            db2.close()
    except Exception:
        pass

    prompt = f"""As a Senior Research Editor, create a HIGH-FIDELITY INSIGHT DIGEST of the following report from {specialist_name} for the CIO.

CRITICAL REQUIREMENTS:
1. PRESERVE ALL SOURCE LINKS AND CITATIONS
2. DENSE KEY INSIGHTS: Capture core arguments and unique observations
3. QUANTITATIVE EVIDENCE: Keep all specific numbers, percentages, and dates
4. CRITICAL RISKS: Ensure risk assessments are detailed

Structure:
- [CORE THESIS & VERDICT]
- [QUANTITATIVE & CRITICAL EVIDENCE]
- [KEY ARGUMENTS & RISKS]

Target Language: {language}

Report:
{report[:15000]}"""

    candidates = [(endpoint_url, model, headers)]
    try:
        candidates += resolve_utility_fallback_candidates()
    except Exception:
        pass

    try:
        return await llm_call_async_with_fallback(candidates, [
            {"role": "system", "content": "You are a Senior Research Editor. Output the digest only, no extra text."},
            {"role": "user", "content": prompt},
        ], temperature=0, timeout=30)
    except Exception as e:
        logger.warning(f"[orchestrator] Summarization failed: {e}")
        return report[:2000]  # fallback truncation


# ---------------------------------------------------------------------------
# Main orchestration entry point
# ---------------------------------------------------------------------------

async def run_team_analysis(
    query: str,
    owner: str,
    endpoint_url: str,
    model: str,
    analysis_id: Optional[str] = None,
    language: Optional[str] = None,
    max_iterations: int = 3,
) -> HedgeFundState:
    """Run the full hedge fund team analysis.

    Returns the final HedgeFundState containing all reports and the synthesis.
    """
    import re

    analysis_id = analysis_id or str(uuid.uuid4())[:12]
    is_chinese = bool(re.search(r'[\u4e00-\u9fa5]', query))
    language = language or ("Chinese" if is_chinese else "English")

    state = HedgeFundState(
        query=query,
        language=language,
        messages=[{"role": "user", "content": query}],
    )

    logger.info(f"[orchestrator] Starting team analysis {analysis_id}: {query[:80]}...")

    while state.iteration < max_iterations:
        state.iteration += 1
        logger.info(f"[orchestrator] Iteration {state.iteration}/{max_iterations}")

        # ── Step 1: Stanley decides routing ──
        roster = _build_team_roster()
        reports_received = ", ".join(state.summaries.keys()) or "None"
        summaries_text = ""
        if state.summaries:
            summaries_text = "\n\n".join(
                f"[{sid.upper()}]: {s[:1500]}"
                for sid, s in state.summaries.items()
            )

        stanley_prompt = STANLEY_SYSTEM_PROMPT.format(
            team_roster=roster,
            iteration=state.iteration,
            reports_received=reports_received,
            language=language,
            summaries=summaries_text or "No findings yet.",
        )

        stanley_messages = [
            {"role": "system", "content": stanley_prompt},
            *[m for m in state.messages[-6:]],  # last few messages for context
        ]

        stanley_raw = await _llm_call_structured(
            endpoint_url, model, stanley_messages, temperature=0.1
        )

        # Extract JSON from possible markdown fences
        json_str = stanley_raw.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        try:
            decision = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(f"[orchestrator] Failed to parse Stanley JSON, trying regex fallback")
            # Last-ditch: find {...} block
            m = re.search(r'\{.*\}', json_str, re.DOTALL)
            if m:
                try:
                    decision = json.loads(m.group())
                except json.JSONDecodeError:
                    logger.error(f"[orchestrator] Unparseable Stanley output: {stanley_raw[:500]}")
                    break
            else:
                logger.error(f"[orchestrator] No JSON found in Stanley output")
                break

        next_agents = decision.get("next_agents", [])
        instructions = decision.get("instructions", query)
        final_synthesis = decision.get("final_synthesis", "")

        state.messages.append({
            "role": "assistant",
            "name": "stanley",
            "content": json.dumps(decision),
        })

        logger.info(f"[orchestrator] Stanley -> next_agents={next_agents}")

        # ── Step 2: Check if done ──
        if not next_agents:
            state.final_answer = final_synthesis
            logger.info(f"[orchestrator] Stanley signaled completion")
            break

        # ── Step 3: Run selected specialists ──
        # P0 agents get full agent loop; P1/P2 get call_specialist tool path
        p0_to_run = [a for a in next_agents if a in P0_IDS]
        p1p2_to_run = [a for a in next_agents if a in P1_IDS or a in P2_IDS]

        # Run P0 agents in parallel
        import asyncio
        p0_results = {}
        if p0_to_run:
            tasks = {}
            for sid in p0_to_run:
                system_prompt = _get_p0_prompt(sid, instructions, language)
                spec = SPECIALIST_DEFS[sid]
                task_key = sid
                tasks[task_key] = asyncio.create_task(
                    _run_agent_loop(
                        endpoint_url=endpoint_url,
                        model=model,
                        system_prompt=system_prompt,
                        user_message=instructions,
                        owner=owner,
                        session_id=f"{analysis_id}-{sid}",
                        enabled_tools=spec["enabled_tools"],
                        max_rounds=15,
                        temperature=spec["temperature"],
                    )
                )
            for task_key, coro in tasks.items():
                try:
                    p0_results[task_key] = await coro
                    logger.info(f"[orchestrator] {task_key} completed ({len(p0_results[task_key])} chars)")
                except Exception as e:
                    logger.error(f"[orchestrator] {task_key} failed: {e}")
                    p0_results[task_key] = f"[Error] {e}"

        # Run P1/P2 specialists via the lighter tool path
        p1p2_results = {}
        if p1p2_to_run:
            tasks = {}
            for sid in p1p2_to_run:
                tasks[sid] = asyncio.create_task(
                    _call_specialist_tool(
                        specialist_id=sid,
                        query=query,
                        instruction=instructions,
                        language=language,
                        endpoint_url=endpoint_url,
                        model=model,
                        owner=owner,
                        analysis_id=analysis_id,
                    )
                )
            for sid, coro in tasks.items():
                try:
                    p1p2_results[sid] = await coro
                    logger.info(f"[orchestrator] {sid} completed ({len(p1p2_results[sid])} chars)")
                except Exception as e:
                    logger.error(f"[orchestrator] {sid} failed: {e}")
                    p1p2_results[sid] = f"[Error] {e}"

        # Merge all results
        all_results = {**p0_results, **p1p2_results}

        # ── Step 4: Summarize each report ──
        summary_tasks = {}
        for sid, report in all_results.items():
            name = SPECIALIST_DEFS.get(sid, {}).get("name", sid)
            summary_tasks[sid] = asyncio.create_task(
                _summarize_report(name, report, language, endpoint_url, model)
            )

        summaries = {}
        for sid, coro in summary_tasks.items():
            try:
                summaries[sid] = await coro
            except Exception as e:
                logger.warning(f"[orchestrator] Summary for {sid} failed: {e}")
                summaries[sid] = all_results.get(sid, "")[:1500]

        # ── Step 5: Update state ──
        state.reports.update(all_results)
        state.summaries.update(summaries)
        state.next_agents = next_agents

        # Add specialist messages to conversation
        for sid, report in all_results.items():
            state.messages.append({
                "role": "assistant",
                "name": sid,
                "content": report[:5000],  # trimmed for context
            })

    # ── Final synthesis if Stanley didn't produce one ──
    if not state.final_answer:
        try:
            synthesis_prompt = f"""You are Stanley Druckenmiller, CIO. Synthesize the following team research reports into a comprehensive executive summary.

User Query: "{query}"

Available Reports:
{chr(10).join(f'=== {sid.upper()} ===\n{r[:3000]}' for sid, r in state.reports.items())}

Provide:
1. **Executive Summary** — 2-3 paragraph high-level verdict
2. **Key Findings by Analyst** — bullet-point summary from each perspective
3. **Risks & Caveats** — what could go wrong
4. **Final Verdict** — actionable conclusion

Output strictly in {language}. Make it professional and hedge-fund quality."""

            synthesis = await _llm_call_structured(
                endpoint_url, model,
                [{"role": "user", "content": synthesis_prompt}],
                temperature=0.2,
            )
            state.final_answer = synthesis
        except Exception as e:
            logger.error(f"[orchestrator] Final synthesis failed: {e}")
            state.final_answer = "Synthesis generation failed."

    logger.info(f"[orchestrator] Analysis {analysis_id} complete. "
                f"Reports: {len(state.reports)}, "
                f"Final: {len(state.final_answer)} chars")
    return state


# ---------------------------------------------------------------------------
# CrewMember seeding (optional — run on startup to create DB records)
# ---------------------------------------------------------------------------

def seed_hedge_fund_crew(owner: str, endpoint_url: str = "", model: str = "") -> dict[str, str]:
    """Create CrewMember records for the hedge fund team (Stanley + 4 P0).

    Returns dict of {specialist_id: crew_member_id}.
    Idempotent — skips existing records with matching is_hedge_fund flag.
    Returns empty dict if database is not available.
    """
    import uuid
    import json
    import logging

    logger = logging.getLogger(__name__)

    try:
        from core.database import SessionLocal, CrewMember
    except ImportError:
        logger.warning("[orchestrator] core.database not available — skipping seed")
        return {}

    hedheg_ids = {"stanley", "jintao", "fundamental", "technician", "riskmaster"}
    created = {}

    db = SessionLocal()
    try:
        existing = db.query(CrewMember).filter(
            CrewMember.owner == owner,
            CrewMember.is_default_assistant == False,  # noqa: E712
        ).all()

        # Check for existing hedge fund members by name match
        existing_names = {c.name for c in existing if c.name}

        for sid in hedheg_ids:
            if sid == "stanley":
                name = "Stanley Druckenmiller"
                special_prompt = STANLEY_SYSTEM_PROMPT
                tools = []
            else:
                spec = SPECIALIST_DEFS.get(sid)
                if not spec:
                    continue
                name = spec["name"]
                special_prompt = P0_SYSTEM_PROMPTS.get(sid, "{instruction}")
                tools = spec.get("enabled_tools", [])

            if name in existing_names:
                logger.info(f"[orchestrator] CrewMember '{name}' already exists — skipping")
                # Still find the ID for the return dict
                match = next((c for c in existing if c.name == name), None)
                if match:
                    created[sid] = match.id
                continue

            crew_id = str(uuid.uuid4())
            member = CrewMember(
                id=crew_id,
                owner=owner,
                name=name,
                avatar=None,
                user_name=None,
                personality=(
                    special_prompt
                    if sid == "stanley"
                    else _get_p0_prompt(sid, "Research the assigned topic.", "English")
                ),
                model=model or None,
                endpoint_url=endpoint_url or None,
                greeting=f"Ready as {name}.",
                enabled_tools=json.dumps(tools) if tools else "[]",
                session_id=None,
                is_active=True,
                sort_order={"stanley": 0, "jintao": 1, "fundamental": 2, "technician": 3, "riskmaster": 4}.get(sid, 10),
                is_default_assistant=False,
                timezone=None,
            )
            db.add(member)
            created[sid] = crew_id
            logger.info(f"[orchestrator] Seeded CrewMember '{name}' ({crew_id})")

        db.commit()
        logger.info(f"[orchestrator] Seeded {len(created)} hedge fund crew members for owner={owner}")
    except Exception as e:
        logger.exception(f"[orchestrator] seed_hedge_fund_crew failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()

    return created
