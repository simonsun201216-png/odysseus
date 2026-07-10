"""
services/data_sync/kb_cleaner.py

ETL pipeline: raw public.meetings → kb_ normalized dimension tables.

Run from the odysseus container:
    docker exec prophetis_dev-odysseus python -m services.data_sync.kb_cleaner

Or via script entry:
    python -m services.data_sync.kb_cleaner [--dry-run]
"""

import argparse
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kb_cleaner")

# ── DB connection ──────────────────────────────────────────────────────────

DB_DSN = os.getenv(
    "PROPHETIS_DB_DSN",
    "postgresql://postgres:postgres@supabase-db:5432/postgres",
)


def get_conn():
    return psycopg2.connect(DB_DSN)


# ── Constants ──────────────────────────────────────────────────────────────

# Separators for multi-company fields
COMPANY_SEP_RE = re.compile(r"[,，、/&]")

# Newline/markdown artifacts in keyword fields
NEWLINE_ARTIFACT_RE = re.compile(r"[\n\r]+")
MARKDOWN_ARTIFACT_RE = re.compile(r"[*_#`]")

# LLM footer / section boundary patterns
LLM_FOOTER_RE = re.compile(
    r"(^(?:thank|thanks|note:|please|feel free|if you|let me|i hope|best|regards|"
    r"here are|here is|sure|based on|certainly|absolutely|below|above|following))",
    re.IGNORECASE,
)
# Section headers that sometimes leak into keyword lists
SECTION_HEADER_RE = re.compile(
    r"^(key\s+(?:points?|topics?|findings?|takeaways?|insights?|highlights?|"
    r"discussions?|themes?|drivers?|risks?|opportunities?|challenges?|"
    r"developments?|trends?|metrics?|questions?))",
    re.IGNORECASE,
)

# Noise keywords — single chars, pure numbers, common filler
STOP_KEYWORDS = frozenset(
    {
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "by",
        "and", "or", "not", "no", "is", "it", "as", "be", "but", "if", "so",
        "we", "he", "she", "they", "do", "has", "had", "can", "may", "will",
        "all", "any", "are", "did", "get", "got", "has", "its", "let", "may",
        "new", "now", "per", "see", "set", "too", "use", "way", "年", "月",
        "日", "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
        "都", "一", "个", "上", "也", "很", "到", "说", "要", "去", "你",
        "会", "着", "没", "看", "好", "自", "己", "这", "中", "与", "及",
        "或", "之", "而", "但", "被", "把", "对", "等", "从", "他", "她",
        "它", "们", "所", "能", "下", "美", "行", "", "none", "n/a", "na",
    }
)

PURE_NUMBER_RE = re.compile(r"^\d+(\.\d+)?$")
SINGLE_CHAR_NON_CN_RE = re.compile(r"^[a-zA-Z0-9]$")

# Date correction map for year 0026/0226 → 2026
YEAR_CORRECTIONS = {
    "0026": "2026",
    "0226": "2026",
}


# ── Helpers ────────────────────────────────────────────────────────────────


def split_companies(raw: Optional[str]) -> list[str]:
    """Split a multi-company string into individual company names."""
    if not raw or not raw.strip():
        return []
    # Normalize full-width punctuation
    cleaned = raw.replace("／", "/").replace("＆", "&")
    parts = [p.strip() for p in COMPANY_SEP_RE.split(cleaned) if p.strip()]
    # Dedup while preserving order
    seen = set()
    result = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def parse_sentiment(raw: Optional[str]) -> Optional[int]:
    """Extract numeric sentiment from raw sentiment string."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    # Pattern: +/-N or "Sentiment: +/-N"
    m = re.search(r"([+-]\d+)", raw)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def clean_date(raw: Optional[str]) -> tuple[Optional[str], bool]:
    """Clean a date string. Returns (cleaned_iso_date, was_corrected)."""
    if not raw or not raw.strip():
        return None, False
    raw = raw.strip()
    # Fix year 0026/0226 → 2026
    for wrong, right in YEAR_CORRECTIONS.items():
        if raw.startswith(wrong):
            raw = right + raw[len(wrong):]
            break
    # Normalize separator
    raw = raw.replace("/", "-")
    return raw, raw != raw.strip()


def clean_keywords(raw: Optional[str]) -> tuple[list[str], list[str]]:
    """Clean and split keyword string. Returns (valid_keywords, noise_keywords)."""
    if not raw or not raw.strip():
        return [], []

    # Step 1: Remove newline artifacts
    text = NEWLINE_ARTIFACT_RE.sub(",", raw)

    # Step 2: Remove markdown
    text = MARKDOWN_ARTIFACT_RE.sub("", text)

    # Step 3: Split by common separators
    tokens = re.split(r"[,，、;；|·•\n\r]+", text)

    valid = []
    noise = []
    for t in tokens:
        t = t.strip().strip("'\".”’\"")
        if not t:
            continue
        # Filter LLM footer / section headers
        if LLM_FOOTER_RE.match(t) or SECTION_HEADER_RE.match(t):
            noise.append(t)
            continue
        # Filter pure numbers
        if PURE_NUMBER_RE.match(t):
            noise.append(t)
            continue
        # Filter single non-CJK char
        if SINGLE_CHAR_NON_CN_RE.match(t):
            noise.append(t)
            continue
        # Filter stop keywords
        if t.lower() in STOP_KEYWORDS:
            noise.append(t)
            continue
        valid.append(t)

    # Dedup while preserving order
    seen = set()
    deduped = []
    for v in valid:
        if v not in seen:
            seen.add(v)
            deduped.append(v)

    return deduped, noise


def extract_entities_from_keywords(
    keywords: list[str],
    canonical_companies: set[str],
) -> list[tuple[str, str, str]]:
    """Extract known company names and other entities from keyword tokens."""
    entities = []
    for kw in keywords:
        if kw in canonical_companies:
            entities.append((kw, "company", kw))
        # Simple: check if any known company is a substring
        for cc in canonical_companies:
            if len(cc) >= 2 and cc in kw:
                entities.append((cc, "company", kw))
                break
    return entities


def build_industry_tree(
    conn,
) -> dict[str, int]:
    """Build industry taxonomy from existing meeting data.

    Returns dict mapping 'l1_name|l2_name' → industry_id.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT DISTINCT industry FROM public.meetings WHERE industry IS NOT NULL AND industry != ''"
        )
        rows = cur.fetchall()

    # Parse existing compound industries
    industry_counts: Counter = Counter()
    compound_count: Counter = Counter()
    for r in rows:
        raw = r["industry"].strip()
        industry_counts[raw] += 1
        # Check for compound patterns with separators
        parts = re.split(r"[,，、;；/&]+", raw)
        if len(parts) > 1:
            for p in parts:
                p = p.strip()
                if p:
                    compound_count[p] += 1

    logger.info(
        "Industry analysis: %d distinct, %d compound patterns detected",
        len(industry_counts),
        len(compound_count),
    )

    # Manual top-level categories mapped from observed industry strings
    # This is a heuristic — will be refined as data populates
    L1_CLASSIFICATION = {
        "工业制造业": ["制造", "工业", "工程机械", "装备", "自动化"],
        "科技互联网": ["科技", "互联网", "软件", "AI", "人工", "数字", "SaaS", "半导体", "芯片"],
        "金融投资": ["金融", "银行", "保险", "证券", "投资", "基金", "资本"],
        "消费零售": ["消费", "零售", "食品", "饮料", "餐饮", "电商", "品牌"],
        "医疗健康": ["医疗", "医药", "健康", "生物", "器械", "医院", "制药"],
        "汽车交通": ["汽车", "新能源车", "交通", "运输", "物流", "出行"],
        "能源环保": ["能源", "电力", "光伏", "风电", "氢能", "储能", "环保", "碳中和"],
        "房地产基建": ["房地产", "地产", "基建", "建筑", "建材"],
        "农业食品": ["农业", "农产品", "养殖", "种植", "畜牧"],
        "教育文化": ["教育", "文化", "传媒", "娱乐", "体育"],
        "通信服务": ["通信", "5G", "电信", "运营商"],
        "其他": [],
    }

    def classify_industry(name: str) -> tuple[str, str]:
        for l1, keywords in L1_CLASSIFICATION.items():
            for kw in keywords:
                if kw.lower() in name.lower():
                    return l1, name
        return "其他", name

    with conn.cursor() as cur:
        # Insert top-level categories first
        for l1 in L1_CLASSIFICATION:
            cur.execute(
                "INSERT INTO kb.industry_tree (l1_name, l2_name, path) "
                "VALUES (%s, NULL, %s) ON CONFLICT (l1_name, l2_name) DO NOTHING",
                (l1, l1),
            )

        # Insert all observed industries as L2 under their classified L1
        inserted = set()
        for raw_name, count in sorted(
            industry_counts.items(), key=lambda x: -x[1]
        ):
            if raw_name in inserted:
                continue
            l1, l2 = classify_industry(raw_name)
            path = f"{l1}.{l2}" if l2 and l2 != l1 else l1
            try:
                cur.execute(
                    "INSERT INTO kb.industry_tree (l1_name, l2_name, path) "
                    "VALUES (%s, %s, %s) ON CONFLICT (l1_name, l2_name) DO NOTHING",
                    (l1, l2 if l2 != l1 else None, path),
                )
                inserted.add(raw_name)
            except Exception:
                pass

        conn.commit()

    # Build lookup
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT industry_id, l1_name, l2_name FROM kb.industry_tree")
        tree = {}
        for r in cur.fetchall():
            key = f"{r['l1_name']}|{r['l2_name'] or ''}"
            tree[key] = r["industry_id"]
        return tree


# ── Main ETL pipeline ──────────────────────────────────────────────────────


def run_etl(dry_run: bool = False):
    """Run the full kb_ ETL pipeline."""
    conn = get_conn()
    try:
        # ── Step 1: Count total meetings ──
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.meetings")
            total = cur.fetchone()[0]
        logger.info("ETL starting: %d meetings to process", total)

        # ── Step 2: Scan distinct companies ──
        logger.info("Step 2: Scanning distinct companies...")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT DISTINCT main_company FROM public.meetings "
                "WHERE main_company IS NOT NULL AND main_company != ''"
            )
            raw_companies = [r["main_company"] for r in cur.fetchall()]
        logger.info("  Found %d distinct raw company values", len(raw_companies))

        # Split and collect all individual company names
        all_individual: Counter = Counter()
        company_to_aliases: dict[str, set[str]] = defaultdict(set)
        for raw in raw_companies:
            parts = split_companies(raw)
            for p in parts:
                all_individual[p] += 1
                company_to_aliases[p].add(raw)

        logger.info("  Found %d unique individual company names", len(all_individual))

        if not dry_run:
            # Insert canonical companies (use the name as-is for now — alias refinement is iterative)
            with conn.cursor() as cur:
                for name, count in sorted(
                    all_individual.items(), key=lambda x: -x[1]
                ):
                    cur.execute(
                        "INSERT INTO kb.companies (canonical) VALUES (%s) "
                        "ON CONFLICT (canonical) DO NOTHING",
                        (name,),
                    )
                # Insert alias mappings
                alias_data = []
                seen_aliases = set()
                for canonical in all_individual:
                    if canonical not in seen_aliases and len(canonical) <= 1024:
                        alias_data.append((canonical, canonical, True))
                        seen_aliases.add(canonical)
                    # The raw strings that resolve TO this name
                    for raw_alias in company_to_aliases.get(canonical, set()):
                        if (raw_alias != canonical and raw_alias.strip()
                                and raw_alias not in seen_aliases
                                and len(raw_alias) <= 1024):
                            alias_data.append((raw_alias, canonical, False))
                            seen_aliases.add(raw_alias)
                execute_values(
                    cur,
                    "INSERT INTO kb.company_aliases (alias, canonical, is_canonical) "
                    "VALUES %s ON CONFLICT (alias) DO NOTHING",
                    alias_data,
                    template="(%s, %s, %s)",
                )
                conn.commit()
            logger.info(
                "  Inserted %d canonical companies, %d alias mappings",
                len(all_individual),
                len(alias_data),
            )

        # ── Step 3: Populate meeting_companies (split multi-company) ──
        logger.info("Step 3: Splitting multi-company records...")
        canonical_companies = set(all_individual.keys())
        meeting_company_data = []
        if not dry_run:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT uid, main_company, mentioned_companies FROM public.meetings "
                    "WHERE main_company IS NOT NULL AND main_company != '' "
                    "   OR mentioned_companies IS NOT NULL AND mentioned_companies != ''"
                )
                for row in cur.fetchall():
                    uid = row["uid"]
                    raw_main = row["main_company"] or ""
                    raw_mentioned = row["mentioned_companies"] or ""

                    # Process companies from both fields
                    seen_here = set()
                    main_parts = split_companies(raw_main)
                    ment_parts = split_companies(raw_mentioned)

                    for idx, company in enumerate(main_parts + ment_parts):
                        if company in seen_here or company not in canonical_companies:
                            continue
                        seen_here.add(company)
                        is_primary = idx < len(main_parts) and company == main_parts[0] if main_parts else False
                        position = idx
                        meeting_company_data.append(
                            (uid, company, raw_main if idx < len(main_parts) and len(main_parts) > 1
                             else raw_mentioned if len(ment_parts) > 1 else None,
                             is_primary, position)
                        )

            with conn.cursor() as cur:
                execute_values(
                    cur,
                    "INSERT INTO kb.meeting_companies "
                    "(uid, company, alias_used, is_primary, position) VALUES %s "
                    "ON CONFLICT (uid, company) DO NOTHING",
                    meeting_company_data,
                    template="(%s, %s, %s, %s, %s)",
                )
                conn.commit()
            logger.info("  Inserted %d meeting-company mappings", len(meeting_company_data))

        # ── Step 4: Build industry tree + populate meeting_industries ──
        logger.info("Step 4: Building industry taxonomy...")
        if not dry_run:
            industry_lookup = build_industry_tree(conn)

            # Map meetings to industries
            meeting_industry_data = []
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT uid, industry FROM public.meetings "
                    "WHERE industry IS NOT NULL AND industry != ''"
                )
                for row in cur.fetchall():
                    uid = row["uid"]
                    raw = row["industry"]
                    # Try exact match first
                    for key, iid in industry_lookup.items():
                        l1, l2 = key.split("|", 1)
                        if l2 and (raw == l2 or raw in l2 or l2 in raw):
                            meeting_industry_data.append((uid, iid, raw))
                            break
                    else:
                        # Classify on the fly
                        for l1_name, keywords in {
                            k: v for k, v in [
                                ("工业制造业", ["制造", "工业", "工程机械", "装备", "自动化"]),
                                ("科技互联网", ["科技", "互联网", "软件", "AI", "人工", "数字", "SaaS", "半导体", "芯片"]),
                                ("金融投资", ["金融", "银行", "保险", "证券", "投资", "基金", "资本"]),
                                ("消费零售", ["消费", "零售", "食品", "饮料", "餐饮", "电商", "品牌"]),
                                ("医疗健康", ["医疗", "医药", "健康", "生物"]),
                                ("汽车交通", ["汽车", "交通", "运输", "物流"]),
                                ("能源环保", ["能源", "电力", "光伏", "风电", "环保", "碳中和"]),
                                ("房地产基建", ["房地产", "地产", "基建"]),
                                ("其他", []),
                            ]
                        }.items():
                            match = False
                            for kw in keywords:
                                if kw.lower() in raw.lower():
                                    match = True
                                    break
                            if match or l1_name == "其他":
                                key = f"{l1_name}|"
                                if key in industry_lookup:
                                    meeting_industry_data.append(
                                        (uid, industry_lookup[key], raw)
                                    )
                                break

            if meeting_industry_data:
                with conn.cursor() as cur:
                    execute_values(
                        cur,
                        "INSERT INTO kb.meeting_industries (uid, industry_id, raw_text) "
                        "VALUES %s ON CONFLICT (uid, industry_id) DO NOTHING",
                        meeting_industry_data,
                        template="(%s, %s, %s)",
                    )
                    conn.commit()
            logger.info(
                "  Inserted %d meeting-industry mappings",
                len(meeting_industry_data),
            )

        # ── Step 5: Clean keywords ──
        logger.info("Step 5: Cleaning keywords...")
        keyword_clean_data = []
        keyword_noise_data = []
        keyword_entity_data = []
        total_noise_count = 0
        total_valid_count = 0

        if not dry_run:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT uid, keywords FROM public.meetings "
                    "WHERE keywords IS NOT NULL AND keywords != ''"
                )
                for row in cur.fetchall():
                    uid = row["uid"]
                    raw = row["keywords"]
                    valid, noise = clean_keywords(raw)
                    for idx, kw in enumerate(valid):
                        keyword_clean_data.append((uid, kw, idx, False))
                        total_valid_count += 1
                    for kw in noise:
                        keyword_noise_data.append((uid, kw, 0, True))
                        total_noise_count += 1
                    # Entity extraction
                    for ent_name, ent_type, src_kw in extract_entities_from_keywords(
                        valid, canonical_companies
                    ):
                        keyword_entity_data.append((uid, ent_name, ent_type, src_kw))

            with conn.cursor() as cur:
                # Clean keywords
                if keyword_clean_data:
                    execute_values(
                        cur,
                        "INSERT INTO kb.meeting_keywords_clean "
                        "(uid, keyword, position, is_noise) VALUES %s "
                        "ON CONFLICT (uid, keyword) DO NOTHING",
                        keyword_clean_data,
                        template="(%s, %s, %s, %s)",
                    )
                if keyword_noise_data:
                    execute_values(
                        cur,
                        "INSERT INTO kb.meeting_keywords_clean "
                        "(uid, keyword, position, is_noise) VALUES %s "
                        "ON CONFLICT (uid, keyword) DO UPDATE SET is_noise=true",
                        keyword_noise_data,
                        template="(%s, %s, %s, %s)",
                    )
                # Entities
                if keyword_entity_data:
                    execute_values(
                        cur,
                        "INSERT INTO kb.keyword_entities (uid, entity, entity_type, keyword) "
                        "VALUES %s ON CONFLICT (uid, entity, entity_type) DO NOTHING",
                        keyword_entity_data,
                        template="(%s, %s, %s, %s)",
                    )
                conn.commit()
            logger.info(
                "  Cleaned keywords: %d valid, %d noise, %d entities extracted",
                total_valid_count,
                total_noise_count,
                len(keyword_entity_data),
            )

        # ── Step 6: Sentiment parsing ──
        logger.info("Step 6: Parsing sentiment...")
        sentiment_data = []
        if not dry_run:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT uid, sentiment FROM public.meetings "
                    "WHERE sentiment IS NOT NULL AND sentiment != ''"
                )
                for row in cur.fetchall():
                    uid = row["uid"]
                    raw = row["sentiment"]
                    val = parse_sentiment(raw)
                    sentiment_data.append((uid, val, raw, val is not None))

            with conn.cursor() as cur:
                execute_values(
                    cur,
                    "INSERT INTO kb.meeting_sentiments (uid, sentiment_val, raw_text, is_parsed) "
                    "VALUES %s ON CONFLICT (uid) DO UPDATE SET "
                    "sentiment_val=EXCLUDED.sentiment_val, is_parsed=EXCLUDED.is_parsed",
                    sentiment_data,
                    template="(%s, %s, %s, %s)",
                )
                conn.commit()
            parsed_count = sum(1 for _, v, _, _ in sentiment_data if v is not None)
            logger.info(
                "  Parsed sentiment: %d records, %d successfully parsed",
                len(sentiment_data),
                parsed_count,
            )

        # ── Step 7: Date cleaning ──
        logger.info("Step 7: Cleaning dates...")
        date_data = []
        if not dry_run:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT uid, meeting_date FROM public.meetings "
                    "WHERE meeting_date IS NOT NULL"
                )
                for row in cur.fetchall():
                    uid = row["uid"]
                    raw = row["meeting_date"]
                    if raw is None:
                        continue
                    cleaned, corrected = clean_date(str(raw))
                    if cleaned:
                        date_data.append((uid, cleaned, str(raw), corrected))

            with conn.cursor() as cur:
                execute_values(
                    cur,
                    "INSERT INTO kb.meeting_dates (uid, meeting_date, raw_date, is_corrected) "
                    "VALUES %s ON CONFLICT (uid) DO UPDATE SET "
                    "meeting_date=EXCLUDED.meeting_date, is_corrected=EXCLUDED.is_corrected",
                    date_data,
                    template="(%s, %s::date, %s, %s)",
                )
                conn.commit()
            corrected = sum(1 for _, _, _, c in date_data if c)
            logger.info(
                "  Cleaned dates: %d records, %d corrected",
                len(date_data),
                corrected,
            )

        # ── Step 8: Source tags ──
        logger.info("Step 8: Normalizing source tags...")
        source_data = []
        if not dry_run:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT uid, source_tag FROM public.meetings "
                    "WHERE source_tag IS NOT NULL AND source_tag != ''"
                )
                for row in cur.fetchall():
                    uid = row["uid"]
                    raw = row["source_tag"].strip()
                    normalized = raw.upper().strip()
                    corrected = normalized != raw
                    source_data.append((uid, normalized, corrected))

            with conn.cursor() as cur:
                execute_values(
                    cur,
                    "INSERT INTO kb.meeting_sources (uid, source_tag, is_corrected) "
                    "VALUES %s ON CONFLICT (uid) DO UPDATE SET "
                    "source_tag=EXCLUDED.source_tag, is_corrected=EXCLUDED.is_corrected",
                    source_data,
                    template="(%s, %s, %s)",
                )
                conn.commit()
            corrected = sum(1 for _, _, c in source_data if c)
            logger.info(
                "  Cleaned sources: %d records, %d corrected", len(source_data), corrected
            )

        # ── Step 9: meeting_lookup (source_id → uid) ──
        logger.info("Step 9: Building meeting lookup table...")
        if not dry_run:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE kb.meeting_lookup")
                cur.execute(
                    """
                    INSERT INTO kb.meeting_lookup (source_id, uid, company, meeting_date, source_tag)
                    SELECT
                        'source_' || LEFT(m.uid, 8),
                        m.uid,
                        (SELECT mc.company FROM kb.meeting_companies mc
                         WHERE mc.uid = m.uid AND mc.is_primary = true LIMIT 1),
                        m.meeting_date,
                        m.source_tag
                    FROM public.meetings m
                    ON CONFLICT (source_id) DO NOTHING
                    """
                )
                conn.commit()
                lookup_count = cur.rowcount
            logger.info("  Built %d lookup entries", lookup_count)

        # ── Step 10: Refresh materialized view ──
        logger.info("Step 10: Refreshing materialized view...")
        if not dry_run:
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW kb.meeting_index")
                conn.commit()
            logger.info("  Materialized view refreshed")

        logger.info("ETL complete. %d meetings processed.", total)

    except Exception as e:
        logger.error("ETL failed: %s", e, exc_info=True)
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="kb_ ETL pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, don't write")
    args = parser.parse_args()

    logger.info("kb_cleaner starting (dry_run=%s)", args.dry_run)
    run_etl(dry_run=args.dry_run)
    logger.info("kb_cleaner finished")


if __name__ == "__main__":
    main()
