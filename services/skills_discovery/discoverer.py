"""Skills discovery orchestrator.

Searches known GitHub repositories and web sources for SKILL.md files,
parses them, scores relevance, detects duplicates against the user's
existing skill library, and stores results in the discovered_skills table.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Classification taxonomy for discovered skills
# ---------------------------------------------------------------------------

CLASSIFICATION_CATEGORIES = {
    "finance": "Financial analysis, hedge fund, investment, trading, portfolio management, stock/crypto market, banking, asset management, quantitative finance",
    "dev": "Software development, programming, coding, debugging, engineering, git, CI/CD, API development, code review, deployment",
    "research": "Deep research, data analysis, investigation, academic research, news analysis, information gathering, due diligence",
    "productivity": "Workflow automation, scheduling, task management, time management, organization, note-taking, personal efficiency",
    "communication": "Email, messaging, notifications, Slack, Telegram, Discord, social media, team communication",
    "data": "Data processing, databases, ETL, vector stores, graph databases, data visualization, data ingestion, web scraping",
    "security": "Cybersecurity, penetration testing, vulnerability scanning, access control, threat detection",
    "creative": "Content creation, writing, design, image generation, video production, copywriting, branding",
    "general": "Skills that don't fit the above categories — miscellaneous, general-purpose, or uncategorized tools",
}

CLASSIFICATION_CATEGORY_LIST = sorted(CLASSIFICATION_CATEGORIES.keys())


def _classify_with_keywords(
    name: str, description: str, tags: Optional[List[str]] = None,
    frontmatter_category: str = "",
) -> str:
    """Keyword-based classification fallback.

    Uses name, description, tags, and original frontmatter category to match
    against known category keywords. Returns 'general' if nothing matches.
    """
    text = " ".join(filter(None, [
        name.lower(),
        description.lower(),
        " ".join((tags or [])).lower(),
        frontmatter_category.lower(),
    ]))

    # Priority-ordered keyword sets (first match wins)
    keyword_map = {
        # Order matters — first match wins. More specific categories first.
        "finance": [
            "finance", "financial", "invest", "investing", "investment", "hedge", "fund",
            "trading", "trade", "stock", "market", "portfolio", "quant", "quantitative",
            "broker", "asset", "capital", "equity", "bond", "crypto", "currency",
            "banking", "bank", "valuation", "income", "revenue", "earnings",
            "sec", "filing", "analyst", "analysis",
        ],
        "data": [
            "data", "database", "etl", "vector", "qdrant", "elasticsearch",
            "neo4j", "graph", "sql", "nosql", "ingest", "scrape", "scraping",
            "crawl", "crawling", "warehouse", "pipeline", "analytics",
            "visualization", "dashboard",
        ],
        "security": [
            "security", "cyber", "cybersecurity", "penetration", "pentest",
            "vulnerability", "cve", "exploit", "threat", "malware", "virus",
            "firewall", "encrypt", "decrypt", "auth", "authentication",
            "authorization", "access control", "compliance", "audit",
        ],
        "research": [
            "research", "deep research", "analysis", "investigate", "investigation",
            "diligence", "due diligence", "study", "report", "discover",
            "findings", "intelligence", "analyst", "threat intelligence",
        ],
        "dev": [
            "dev", "development", "programming", "program", "code", "coding",
            "software", "engineering", "engineer", "git", "github", "commit",
            "deploy", "debug", "debugging", "api", "rest", "graphql", "sdk",
            "library", "package", "module", "framework", "compiler", "build",
            "refactor", "test", "testing", "type", "typescript", "python",
            "javascript", "react", "docker", "kubernetes", "ci/cd",
        ],
        "communication": [
            "email", "mail", "message", "messaging", "slack", "telegram",
            "discord", "notification", "notify", "communicate", "communication",
            "social", "sms", "push", "alert", "webhook",
        ],
        "productivity": [
            "productivity", "workflow", "automation", "automate", "schedule",
            "scheduling", "task", "todo", "organize", "organization",
            "calendar", "reminder", "note", "notes", "efficiency",
            "template", "boilerplate", "shortcut", "macro",
        ],
        "creative": [
            "creative", "content", "writing", "write", "copy", "copywriting",
            "design", "designer", "image", "video", "audio", "multimedia",
            "brand", "branding", "art", "illustration", "animation",
            "presentation", "slide", "document",
        ],
    }

    for cat, keywords in keyword_map.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "general"


def _classify_batch_with_llm(
    skills: List[Dict[str, Any]],
) -> Optional[Dict[str, str]]:
    """Classify a batch of skills using the LLM, returning {skill_key: auto_category}.

    Uses the configured OpenAI-compatible endpoint. Falls back to None on
    any failure so the caller can use keyword classification instead.

    Batches multiple skills in one LLM call to minimize API overhead.
    """
    if not skills:
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    llm_host = os.getenv("LLM_HOST", "localhost")
    if not api_key:
        logger.info("No OPENAI_API_KEY set — skipping LLM classification, using keywords")
        return None

    # Build a compact representation of all skills to classify
    skill_entries = []
    for i, sk in enumerate(skills):
        name = sk.get("name", "unnamed")
        desc = (sk.get("description") or "")[:300]
        fm = sk.get("raw_metadata", {}).get("frontmatter", {})
        orig_cat = str(fm.get("category", "") or "")
        tags = ", ".join(str(t) for t in _as_list(fm.get("tags", [])))
        skill_entries.append(f"[{i}] name={name} | desc={desc} | category={orig_cat} | tags={tags}")

    category_descriptions = "\n".join(
        f"  - {cat}: {desc}"
        for cat, desc in CLASSIFICATION_CATEGORIES.items()
    )

    prompt = f"""You are a skill classifier. For each skill below, choose the single best category.

Available categories:
{category_descriptions}

Respond with a JSON object where keys are the skill index numbers and values are the category names.
Only use categories from the list above. If none fit, use "general".

Skills:
{chr(10).join(skill_entries)}

JSON response (no markdown, no explanation):"""

    try:
        import httpx
        endpoint = f"http://{llm_host}:8000/v1/chat/completions"
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a precise skill classifier. Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            content = body["choices"][0]["message"]["content"].strip()

        # Parse JSON response — handle both ```json ... ``` and raw JSON
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            content = content.rsplit("```", 1)[0].strip()
        result: Dict[str, str] = json.loads(content)

        # Validate categories
        valid = set(CLASSIFICATION_CATEGORIES.keys())
        for k, v in result.items():
            if v not in valid:
                result[k] = "general"

        logger.info(f"LLM classified {len(result)} skills")
        return result

    except Exception as e:
        logger.warning(f"LLM classification failed, falling back to keywords: {e}")
        return None


def _classify_skill(sk: Dict[str, Any]) -> str:
    """Classify a single skill using keyword fallback.

    Used when LLM batch classification is unavailable or for skills
    not covered in the LLM batch result.
    """
    name = sk.get("name", "")
    description = sk.get("description", "")
    fm = sk.get("raw_metadata", {}).get("frontmatter", {})
    tags = _as_list(fm.get("tags", []))
    orig_cat = str(fm.get("category", "") or "")
    return _classify_with_keywords(name, description, tags, orig_cat)


# ---------------------------------------------------------------------------
# Known high-reputation sources (auto-publish on import)
# ---------------------------------------------------------------------------

HIGH_REPUTATION_REPOS = {
    "ChuckSRQ/awesome-hermes-skills",      # 60+ curated skills
    "itgoyo/hermes-skills",                # 310+ skills
    "kevinnft/ai-agent-skills",            # 191 skills, well-structured
    "NousResearch/hermes-skills",           # Hermes official
}

MEDIUM_REPUTATION_REPOS = {
    "xiaohei-info/oh-my-agent-skills",     # bundled skills
    "dwrtz/hermes-skills",                 # community fork
}

# Known source URLs for raw SKILL.md content from awesome-hermes-skills
KNOWN_SOURCES: List[Dict[str, str]] = [
    # These are crawled dynamically; static entries are fallback anchors
    {"type": "github", "repo": "ChuckSRQ/awesome-hermes-skills", "path": ""},
    {"type": "github", "repo": "itgoyo/hermes-skills", "path": ""},
    {"type": "github", "repo": "kevinnft/ai-agent-skills", "path": ""},
]

DEFAULT_SEARCH_QUERIES = [
    "SKILL.md hermes skill",
    "site:github.com SKILL.md frontmatter name description category tags",
    "hermes skill finance analysis",
    "hermes skill research deep",
    "site:github.com hermes-skills SKILL.md",
    "site:github.com awesome-hermes-skills",
]


# ---------------------------------------------------------------------------
# Slugify (mirrors skill_format.slugify to avoid import cycle on startup)
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, fallback: str = "skill") -> str:
    s = str(text or "").strip().lower()
    s = _SLUG_RE.sub("-", s)
    s = s.strip("-")
    return (s or fallback)[:60]


# ---------------------------------------------------------------------------
# Tokenizer for dedup (mirrors skills.py)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set:
    return {w.strip('.,!?";:()[]') for w in (text or "").lower().split() if len(w) > 1}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Source reputation lookup
# ---------------------------------------------------------------------------

def _reputation_for(repo: Optional[str]) -> str:
    if not repo:
        return "medium"
    repo_lower = repo.lower()
    for r in HIGH_REPUTATION_REPOS:
        if r.lower() in repo_lower or repo_lower in r.lower():
            return "high"
    for r in MEDIUM_REPUTATION_REPOS:
        if r.lower() in repo_lower or repo_lower in r.lower():
            return "medium"
    return "low"


def _auto_publish(reputation: str) -> bool:
    """High-reputation sources auto-publish on import; others go draft."""
    return reputation == "high"


# ---------------------------------------------------------------------------
# Remote SKILL.md parser
# ---------------------------------------------------------------------------

def _parse_remote_skill_md(text: str, source_url: str) -> Optional[Dict[str, Any]]:
    """Parse a raw SKILL.md from a remote source into a discovery record.

    Returns a dict with the skill's extracted fields, or None if unparseable.
    Handles both the full frontmatter format and free-form markdown.
    """
    if not text or not text.strip():
        return None

    # Try full frontmatter parse first
    fm, body = _parse_frontmatter(text)
    name = _slugify(
        fm.get("name") or fm.get("description") or _infer_name_from_url(source_url) or "unnamed"
    )
    if not name or name == "unnamed":
        return None

    description = str(fm.get("description", "") or "")
    category = str(fm.get("category", "general") or "general")
    tags = _as_list(fm.get("tags", []))
    when_to_use = _extract_section(body, "when to use")
    procedure = _extract_list_section(body, ("procedure", "steps"))
    pitfalls = _extract_list_section(body, ("pitfalls",))
    verification = _extract_list_section(body, ("verification",))
    platforms = _as_list(fm.get("platforms", []))
    requires_toolsets = _as_list(fm.get("requires_toolsets", []))
    fallback_for_toolsets = _as_list(fm.get("fallback_for_toolsets", []))
    confidence = _as_float(fm.get("confidence", 0.8), 0.8)

    # If no frontmatter parsed at all, use the first heading as description
    if not fm and not description:
        description = _infer_description_from_body(body) or ""

    return {
        "name": name,
        "description": description[:200],
        "category": category[:40],
        "tags": tags[:20],
        "when_to_use": when_to_use[:2000],
        "procedure": procedure[:50],
        "pitfalls": pitfalls[:20],
        "verification": verification[:10],
        "platforms": platforms[:10],
        "requires_toolsets": requires_toolsets[:10],
        "fallback_for_toolsets": fallback_for_toolsets[:10],
        "confidence": confidence,
        "source_url": source_url,
        "raw_metadata": {"frontmatter": fm, "body_preview": body[:500]},
        "relevance_score": 0,
        "similarity_to_existing": 0,
        "matched_to_skill": None,
    }


def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    """Minimal YAML frontmatter parser (mirrors skill_format.py)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_text = text[3:end].lstrip("\n")
    body = text[end + 4:].lstrip("\n")
    fm: Dict[str, Any] = {}
    pending_key: Optional[str] = None
    for line in fm_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([a-z_][a-z0-9_]*):\s*(.*)$", line, re.IGNORECASE)
        if m:
            key, val = m.group(1), m.group(2)
            if val.strip() == "" or val is None:
                pending_key = key
                fm[key] = []
            else:
                fm[key] = _parse_scalar(val)
                pending_key = None
            continue
        m2 = re.match(r"^\s*-\s*(.*)$", line)
        if m2 and pending_key:
            existing = fm.get(pending_key)
            if not isinstance(existing, list):
                fm[pending_key] = []
            fm[pending_key].append(_parse_scalar(m2.group(1)))
    return fm, body


def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(p.strip()) for p in _split_top_level(inner, ",")]
    if raw.lower() in ("true", "yes"):
        return True
    if raw.lower() in ("false", "no"):
        return False
    if raw.lower() in ("null", "none", "~"):
        return None
    if raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass
    return raw


def _split_top_level(s: str, sep: str) -> List[str]:
    out, buf, depth, quote = [], [], 0, None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return out


def _extract_section(body: str, heading: str) -> str:
    """Extract text under a ## heading."""
    m = re.search(
        rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)",
        body, re.M | re.S
    )
    return m.group(1).strip() if m else ""


def _extract_list_section(body: str, headings: tuple) -> List[str]:
    """Extract bullet/numbered list items under any of the given headings."""
    for h in headings:
        section = _extract_section(body, h)
        if section:
            items = []
            for line in section.splitlines():
                s = line.strip()
                if not s:
                    continue
                m = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", s)
                if m:
                    items.append(m.group(1).strip())
                elif items:
                    items[-1] = items[-1] + " " + s
            return items
    return []


def _infer_name_from_url(url: str) -> Optional[str]:
    """Guess a skill name from its URL path.
    
    e.g. https://raw.githubusercontent.com/.../deep-research/SKILL.md → deep-research
    """
    url = url.rstrip("/")
    if url.endswith("SKILL.md"):
        url = url[:-8].rstrip("/")
    name = url.split("/")[-1] if "/" in url else url
    name = re.sub(r"[^a-zA-Z0-9_-]", "", name)
    return name[:60] if name else None


def _infer_description_from_body(body: str) -> str:
    """Use the first sentence of the body as a fallback description."""
    clean = re.sub(r"^##\s+.*$", "", body, flags=re.M).strip()
    first_line = clean.split("\n")[0] if clean else ""
    return first_line[:200]


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x not in (None, "")]
    return [str(v)]


def _as_float(v: Any, default: float = 0.8) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# SkillsDiscoveryService
# ---------------------------------------------------------------------------

class SkillsDiscoveryService:
    """Orchestrates skill discovery from external sources.

    Coordinates GitHub crawling, web search fallback, parsing, dedup against
    the user's existing library, relevance scoring, and DB persistence.
    """

    def __init__(self, db_session_factory=None):
        """db_session_factory: a callable that returns a new SQLAlchemy Session."""
        self._db_factory = db_session_factory
        self._http_client = None  # lazy init

    # ------------------------------------------------------------------
    # GitHub source crawling
    # ------------------------------------------------------------------

    def discover_from_github_repo(self, repo: str, owner: Optional[str] = None) -> List[Dict]:
        """Crawl a GitHub repo for SKILL.md files.

        Uses the GitHub REST API (unauthenticated for public repos).
        Falls back to raw.githubusercontent.com direct fetch.

        Returns a list of discovered skill dicts.
        """
        import urllib.request
        import urllib.error

        skills: List[Dict] = []

        # Try GitHub API to list contents
        api_url = f"https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1"
        try:
            req = urllib.request.Request(api_url, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "odysseus-skills-discovery/1.0",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            skill_files = [
                item for item in (data.get("tree") or [])
                if item.get("type") == "blob"
                and item.get("path", "").endswith("SKILL.md")
            ]

            if not skill_files:
                logger.info(f"No SKILL.md files found in {repo}")
                return skills

            for file_info in skill_files:
                path = file_info["path"]
                # Extract category from path: e.g. "skills/research/deep-research/SKILL.md"
                # or "research/deep-research/SKILL.md"
                parts = path.split("/")
                category = "general"
                if len(parts) >= 3:
                    category = parts[-3] if parts[-1] == "SKILL.md" else "general"

                raw_url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
                skill = self._fetch_and_parse_skill(raw_url, repo, category, owner)
                if skill:
                    # Add path context
                    skill["source_path"] = path
                    skill["category"] = category
                    skills.append(skill)

            logger.info(f"Discovered {len(skills)} skill(s) from {repo}")

        except urllib.error.HTTPError as e:
            if e.code == 403:
                logger.warning(f"GitHub API rate limited for {repo}, trying web search fallback")
            elif e.code == 404:
                logger.info(f"Repo not found: {repo}")
            else:
                logger.warning(f"GitHub API error for {repo}: HTTP {e.code}")
        except Exception as e:
            logger.warning(f"Failed to crawl {repo}: {e}")

        return skills

    def _fetch_and_parse_skill(
        self, raw_url: str, repo: str, category: str,
        owner: Optional[str] = None,
    ) -> Optional[Dict]:
        """Fetch a SKILL.md from a raw URL and parse it."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(raw_url, headers={"User-Agent": "odysseus/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8")
        except Exception as e:
            logger.debug(f"Failed to fetch {raw_url}: {e}")
            return None

        parsed = _parse_remote_skill_md(text, raw_url)
        if not parsed:
            return None

        parsed["source_repo"] = repo
        parsed["source_type"] = "github"
        parsed["category"] = category or parsed.get("category", "general")
        parsed["source_reputation"] = _reputation_for(repo)
        return parsed

    # ------------------------------------------------------------------
    # Web search fallback
    # ------------------------------------------------------------------

    def discover_from_web_search(
        self, queries: Optional[List[str]] = None,
        max_results: int = 10,
        owner: Optional[str] = None,
    ) -> List[Dict]:
        """Search the web for SKILL.md files and parse results.

        Uses the project's existing SearchService or comprehensive_web_search.
        """
        queries = queries or DEFAULT_SEARCH_QUERIES
        seen_urls: set = set()
        skills: List[Dict] = []

        for query in queries[:4]:  # cap queries to avoid excessive calls
            try:
                from services.search import comprehensive_web_search
                _context, sources = comprehensive_web_search(
                    query, max_pages=3, return_sources=True,
                )
            except Exception as e:
                logger.debug(f"Web search for {query!r} failed: {e}")
                continue

            for src in (sources or []):
                url = str(src.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Try to fetch the URL and check if it's a SKILL.md
                skill = self._fetch_and_parse_skill(
                    url, "", "general", owner
                )
                if skill:
                    skill["source_type"] = "websearch"
                    skill["source_reputation"] = "low"
                    skills.append(skill)

                if len(skills) >= max_results:
                    break
            if len(skills) >= max_results:
                break

        return skills

    # ------------------------------------------------------------------
    # Relevance scoring
    # ------------------------------------------------------------------

    def score_relevance(
        self, discovered: Dict[str, Any],
        project_keywords: Optional[List[str]] = None,
    ) -> int:
        """Score a discovered skill's relevance to the project (0-100).

        Considers:
        - Category match (finance, research, data → higher)
        - Tag overlap with project keywords
        - Procedure specificity (more steps = more useful)
        - Confidence score
        """
        project_keywords = project_keywords or [
            "finance", "financial", "investment", "research", "analysis",
            "data", "trading", "market", "portfolio", "stock",
            "report", "insight", "intelligence", "quant", "python",
        ]

        score = 0

        # Category bonus
        category = str(discovered.get("category", "")).lower()
        cat_bonus = {
            "finance": 30, "research": 25, "data": 20, "analysis": 20,
            "dev": 10, "general": 5,
        }
        score += cat_bonus.get(category, 5)

        # Tag/bonus overlap
        tag_text = " ".join(str(t) for t in (discovered.get("tags") or []))
        name_desc = f"{discovered.get('name', '')} {discovered.get('description', '')}"
        combined = (tag_text + " " + name_desc).lower()

        for kw in project_keywords:
            if kw in combined:
                score += 10

        # Procedure bonus (more steps = more substantive)
        proc_count = len(discovered.get("procedure") or [])
        score += min(proc_count * 2, 15)

        # Confidence bonus
        conf = float(discovered.get("confidence", 0.8))
        score += int(conf * 10)

        # Cap at 100
        return min(score, 100)

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def detect_duplicates(
        self, discovered: Dict[str, Any],
        existing_skills: List[Dict[str, Any]],
    ) -> Tuple[int, Optional[str]]:
        """Check if a discovered skill duplicates an existing one.

        Returns (similarity_pct, matched_skill_name) where 0 = no match.
        Similarity is Jaccard over name + description + tags + when_to_use.
        Threshold for "match" is ≥ 0.38 (same as SkillsManager's duplicate blocker).
        """
        cand_text = " ".join([
            str(discovered.get("name", "")),
            str(discovered.get("description", "")),
            str(discovered.get("when_to_use", "")),
            " ".join(str(t) for t in (discovered.get("tags") or [])),
            " ".join(str(t) for t in (discovered.get("procedure") or [])),
        ])
        cand_tokens = _tokenize(cand_text)

        if not cand_tokens:
            return 0, None

        best_score = 0.0
        best_name: Optional[str] = None

        for existing in existing_skills:
            ex_text = " ".join([
                str(existing.get("name", "")),
                str(existing.get("description", "")),
                str(existing.get("when_to_use", "")),
                " ".join(str(t) for t in (existing.get("tags") or [])),
                " ".join(str(t) for t in (existing.get("procedure") or [])),
            ])
            ex_tokens = _tokenize(ex_text)
            sim = _jaccard(cand_tokens, ex_tokens)
            if sim > best_score:
                best_score = sim
                best_name = existing.get("name")

        pct = int(best_score * 100)

        # Only return a "match" above the threshold
        if best_score >= 0.38:
            return min(pct, 100), best_name

        return pct, None

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------

    def store_discovered(
        self, skills: List[Dict[str, Any]],
        owner: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Store discovered skills in the DB. Returns the stored records."""
        from core.database import SessionLocal, DiscoveredSkill

        stored: List[Dict] = []
        db = SessionLocal()
        try:
            for sk in skills:
                # Dedup by source_url for the same owner
                existing = db.query(DiscoveredSkill).filter(
                    DiscoveredSkill.source_url == sk.get("source_url", ""),
                    DiscoveredSkill.owner == owner,
                ).first()
                if existing:
                    logger.debug(f"Already discovered: {sk.get('name')} from {sk.get('source_url')}")
                    continue

                # Auto-match status: if high-similarity duplicate, mark as duplicate
                status = "new"
                matched_to = sk.get("matched_to_skill")
                if matched_to:
                    status = "duplicate"

                # Extract original category from frontmatter or path-based category
                fm = sk.get("raw_metadata", {}).get("frontmatter", {})
                raw_category = str(fm.get("category", sk.get("category", "general")) or "general")[:40]
                auto_category = str(sk.get("auto_category", "general"))[:40]

                record = DiscoveredSkill(
                    id=uuid.uuid4().hex,
                    owner=owner,
                    source_url=str(sk.get("source_url", ""))[:1024],
                    source_repo=str(sk.get("source_repo") or "")[:200],
                    source_type=str(sk.get("source_type", "github"))[:20],
                    name=str(sk.get("name", ""))[:120],
                    description=str(sk.get("description", ""))[:500],
                    raw_metadata=json.dumps(sk.get("raw_metadata", {}), ensure_ascii=False)[:10000],
                    category=raw_category,
                    auto_category=auto_category,
                    relevance_score=sk.get("relevance_score", 0),
                    source_reputation=str(sk.get("source_reputation") or "")[:10],
                    similarity_to_existing=sk.get("similarity_to_existing", 0),
                    matched_to_skill=str(matched_to or "")[:120] if matched_to else None,
                    popularity_score=sk.get("popularity_score", 0),
                    status=status,
                )
                db.add(record)
                db.flush()
                stored.append({
                    "id": record.id,
                    "name": record.name,
                    "description": record.description,
                    "source_url": record.source_url,
                    "source_repo": record.source_repo,
                    "source_type": record.source_type,
                    "category": record.category,
                    "auto_category": record.auto_category,
                    "source_reputation": record.source_reputation,
                    "relevance_score": record.relevance_score,
                    "similarity_to_existing": record.similarity_to_existing,
                    "matched_to_skill": record.matched_to_skill,
                    "popularity_score": record.popularity_score,
                    "status": record.status,
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                })

            db.commit()
            logger.info(f"Stored {len(stored)} new discovered skill(s) for owner={owner}")

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to store discovered skills: {e}")
        finally:
            db.close()

        return stored

    # ------------------------------------------------------------------
    # Import a discovered skill
    # ------------------------------------------------------------------

    def import_skill(
        self, discovery_id: str, skills_manager,
        owner: Optional[str] = None,
        publish: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Import a discovered skill into the user's skill library.

        Args:
            discovery_id: DiscoveredSkill DB record ID
            skills_manager: SkillsManager instance for add_skill
            owner: username
            publish: override auto-publish decision (True=published, False=draft, None=auto)

        Returns: the created skill dict, or None on failure.
        """
        from core.database import SessionLocal, DiscoveredSkill

        db = SessionLocal()
        try:
            record = db.query(DiscoveredSkill).filter(
                DiscoveredSkill.id == discovery_id,
                DiscoveredSkill.owner == owner,
            ).first()
            if not record:
                logger.warning(f"Discovery record not found: {discovery_id}")
                return None
            if record.status in ("imported", "rejected"):
                logger.info(f"Discovery record {discovery_id} already {record.status}")
                return None

            # Parse raw metadata
            meta = {}
            if record.raw_metadata:
                try:
                    meta = json.loads(record.raw_metadata)
                except Exception:
                    pass
            fm = meta.get("frontmatter") or {}

            # Determine publish status
            if publish is None:
                reputation = record.source_reputation or "medium"
                should_publish = _auto_publish(reputation)
            else:
                should_publish = publish

            # Import via SkillsManager
            result = skills_manager.add_skill(
                name=record.name,
                description=record.description,
                category=str(fm.get("category", record.source_type or "general"))[:40],
                tags=_as_list(fm.get("tags", [])),
                platforms=_as_list(fm.get("platforms", [])),
                requires_toolsets=_as_list(fm.get("requires_toolsets", [])),
                fallback_for_toolsets=_as_list(fm.get("fallback_for_toolsets", [])),
                when_to_use=record.raw_metadata[:2000] if record.raw_metadata else "",
                procedure=_as_list(fm.get("procedure", [])),
                pitfalls=_as_list(fm.get("pitfalls", [])),
                verification=_as_list(fm.get("verification", [])),
                status="published" if should_publish else "draft",
                confidence=float(fm.get("confidence", 0.8)),
                source="imported",
                owner=owner,
            )

            if result:
                imported_name = result.get("name", record.name)
                record.status = "imported"
                record.imported_skill_name = imported_name
                record.imported_at = datetime.utcnow()
                record.review_decision = "approve"
                record.popularity_score = (record.popularity_score or 0) + 1
                db.commit()
                logger.info(
                    f"Imported skill '{imported_name}' from discovery {discovery_id} "
                    f"({'published' if should_publish else 'draft'})"
                )

            return result

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to import discovery {discovery_id}: {e}")
            return None
        finally:
            db.close()

    # ------------------------------------------------------------------
    # One-shot discovery pipeline
    # ------------------------------------------------------------------

    def run_discovery(
        self,
        owner: Optional[str] = None,
        existing_skills: Optional[List[Dict]] = None,
        repo: Optional[str] = None,
        queries: Optional[List[str]] = None,
        project_keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Run the full discovery pipeline: crawl → parse → score → dedup → store.

        Args:
            owner: username for ownership
            existing_skills: list of user's existing skills (for dedup)
            repo: specific GitHub repo to scan (None = scan all known)
            queries: web search queries (None = use defaults)
            project_keywords: relevance scoring keywords

        Returns: list of newly stored discovery records.
        """
        all_discovered: List[Dict] = []
        repos_to_scan = [repo] if repo else [s["repo"] for s in KNOWN_SOURCES]

        # Phase 1: GitHub crawl
        for r in repos_to_scan:
            try:
                results = self.discover_from_github_repo(r, owner=owner)
                all_discovered.extend(results)
            except Exception as e:
                logger.warning(f"GitHub crawl failed for {r}: {e}")

        # Phase 2: Web search fallback (only if GitHub returned little)
        if len(all_discovered) < 3:
            try:
                results = self.discover_from_web_search(
                    queries=queries, max_results=5, owner=owner,
                )
                all_discovered.extend(results)
            except Exception as e:
                logger.warning(f"Web search discovery failed: {e}")

        if not all_discovered:
            logger.info("No skills discovered in this run")
            return []

        # Phase 3: Score + dedup
        existing = existing_skills or []
        for sk in all_discovered:
            sk["relevance_score"] = self.score_relevance(sk, project_keywords)
            sim_pct, matched = self.detect_duplicates(sk, existing)
            sk["similarity_to_existing"] = sim_pct
            sk["matched_to_skill"] = matched

        # Phase 3b: LLM classification (batch)
        try:
            llm_results = _classify_batch_with_llm(all_discovered)
            for idx, sk in enumerate(all_discovered):
                idx_key = str(idx)
                if llm_results and idx_key in llm_results:
                    sk["auto_category"] = llm_results[idx_key]
                else:
                    sk["auto_category"] = _classify_skill(sk)
                # Always store original category from frontmatter
                fm = sk.get("raw_metadata", {}).get("frontmatter", {})
                sk["category"] = str(fm.get("category", sk.get("category", "general")) or "general")[:40]
        except Exception as e:
            logger.warning(f"Classification error, using keyword fallback: {e}")
            for sk in all_discovered:
                sk["auto_category"] = _classify_skill(sk)
                fm = sk.get("raw_metadata", {}).get("frontmatter", {})
                sk["category"] = str(fm.get("category", sk.get("category", "general")) or "general")[:40]

        # Sort by relevance, take top N
        all_discovered.sort(key=lambda s: s.get("relevance_score", 0), reverse=True)

        # Phase 4: Store
        stored = self.store_discovered(all_discovered, owner=owner)
        return stored

    # ------------------------------------------------------------------
    # List discovered skills from DB
    # ------------------------------------------------------------------

    def list_discovered(
        self, owner: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        sort_by: str = "time",
        limit: int = 100,
    ) -> List[Dict]:
        """List discovered skills from the DB.

        Args:
            owner: filter by owner
            status: filter by status (new/reviewed/imported/rejected/duplicate)
            category: filter by auto_category (finance/dev/research/etc.)
            sort_by: "time" (newest first) or "popularity" (most imported first)
            limit: max records to return
        """
        from core.database import SessionLocal, DiscoveredSkill

        db = SessionLocal()
        try:
            q = db.query(DiscoveredSkill).filter(DiscoveredSkill.owner == owner)
            if status:
                q = q.filter(DiscoveredSkill.status == status)
            if category:
                q = q.filter(DiscoveredSkill.auto_category == category)

            if sort_by == "popularity":
                q = q.order_by(DiscoveredSkill.popularity_score.desc(), DiscoveredSkill.created_at.desc())
            else:
                q = q.order_by(DiscoveredSkill.created_at.desc())

            records = q.limit(limit).all()

            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "source_url": r.source_url,
                    "source_repo": r.source_repo,
                    "source_type": r.source_type,
                    "category": r.category,
                    "auto_category": r.auto_category,
                    "source_reputation": r.source_reputation,
                    "relevance_score": r.relevance_score,
                    "similarity_to_existing": r.similarity_to_existing,
                    "matched_to_skill": r.matched_to_skill,
                    "popularity_score": r.popularity_score,
                    "status": r.status,
                    "review_decision": r.review_decision,
                    "review_note": r.review_note,
                    "reviewed_by": r.reviewed_by,
                    "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                    "imported_skill_name": r.imported_skill_name,
                    "imported_at": r.imported_at.isoformat() if r.imported_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "raw_metadata": json.loads(r.raw_metadata) if r.raw_metadata else None,
                }
                for r in records
            ]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Review / reject
    # ------------------------------------------------------------------

    def review_discovered(
        self, discovery_id: str, owner: str,
        decision: str, note: Optional[str] = None,
    ) -> bool:
        """Approve or reject a discovered skill.

        Args:
            decision: "approve" or "reject"
            note: optional review comment

        Returns: True on success.
        """
        from core.database import SessionLocal, DiscoveredSkill

        db = SessionLocal()
        try:
            record = db.query(DiscoveredSkill).filter(
                DiscoveredSkill.id == discovery_id,
                DiscoveredSkill.owner == owner,
            ).first()
            if not record:
                return False
            if record.status in ("imported",):
                return False  # already imported

            record.status = "reviewed"
            record.review_decision = decision
            if note:
                record.review_note = note[:500]
            record.reviewed_by = owner
            record.reviewed_at = datetime.utcnow()
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to review discovery {discovery_id}: {e}")
            return False
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Delete a discovery record
    # ------------------------------------------------------------------

    def delete_discovered(self, discovery_id: str, owner: str) -> bool:
        """Delete a discovery record."""
        from core.database import SessionLocal, DiscoveredSkill

        db = SessionLocal()
        try:
            record = db.query(DiscoveredSkill).filter(
                DiscoveredSkill.id == discovery_id,
                DiscoveredSkill.owner == owner,
            ).first()
            if not record:
                return False
            db.delete(record)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete discovery {discovery_id}: {e}")
            return False
        finally:
            db.close()
