"""Search routes — /api/search/config GET, /api/search POST, /api/search/intent, /api/search/suggest."""

import logging
import re
from typing import Dict, Any, Optional

from fastapi import APIRouter, Query, Request

import time

from services.search import get_search_config, comprehensive_web_search, PROVIDER_INFO
from services.search.core import _call_provider
from services.search.providers import _get_provider_key, _get_search_instance

logger = logging.getLogger(__name__)


async def _request_values(request: Request) -> Dict[str, Any]:
    """Accept JSON, form data, or query params for search endpoints.

    The browser UI posts FormData, while the agent's generic app_api tool
    posts JSON. FastAPI Form(...) rejects JSON with a 422 before our handler
    runs, which made the model think SearXNG was broken.
    """
    values: Dict[str, Any] = dict(request.query_params)
    content_type = (request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in content_type:
            body = await request.json()
            if isinstance(body, dict):
                values.update(body)
        else:
            form = await request.form()
            values.update(dict(form))
    except Exception:
        pass
    return values


# ── Common US stock tickers (subset used for server-side validation) ──
_COMMON_TICKERS = {
    "AAPL","MSFT","GOOGL","GOOG","AMZN","NVDA","META","TSLA",
    "NFLX","ADBE","CRM","INTC","AMD","IBM","ORCL","CSCO","QCOM",
    "UBER","LYFT","SNAP","PINS","SPOT","RBLX","PLTR","SNOW","DDOG",
    "ZM","DOCU","SQ","SHOP","WDAY","NOW","PANW","FTNT","CRWD",
    "ZS","JPM","BAC","WFC","C","GS","MS","BLK","SCHW","AXP","V","MA",
    "UNH","JNJ","PFE","ABBV","MRK","ABT","TMO","LLY",
    "AMGN","GILD","VRTX","REGN","ISRG","SYK",
    "WMT","COST","HD","LOW","TGT","SBUX","MCD","CMG",
    "NKE","LULU","DIS","CMCSA","ROKU",
    "XOM","CVX","COP","SLB","OXY","MPC",
    "CAT","DE","BA","LMT","GD","NOC","RTX","GE","HON","MMM",
    "T","VZ","TMUS","CHTR",
    "SPY","QQQ","DIA","IWM","VTI","VOO","GLD","SLV",
    "XLF","XLK","XLV","XLI","XLE","XLU",
    "BABA","JD","PDD","BIDU","NIO","LI",
    "NEE","DUK","SO","WM","RSG","ECL","SHW","LIN",
}

_EXCHANGE_SUFFIXES = (".TO", ".V", ".L", ".DE", ".PA", ".MI", ".HK", ".T", ".KS")

# Stoplist: common uppercase words that should NOT be treated as tickers
_TICKER_STOPLIST = frozenset({
    "AI", "IT", "OK", "GO", "NO", "TO", "BY", "AT", "IN", "IS", "IT", "ON",
    "UP", "WE", "US", "MY", "ME", "TV", "CD", "DVD", "CEO", "CTO", "CFO",
    "COO", "USA", "UK", "EU", "UN", "CEO", "GDP", "IPO", "ETF", "REIT",
    "ROI", "EPS", "PE", "API", "AIML", "HTML", "CSS", "JS", "TS",
    "SELL", "BUY", "HOLD", "TOP", "NEWS", "BIG", "NEW", "OLD", "HOT",
    "FED", "SEC", "IRS", "FDIC", "WTO", "IMF", "WHO", "NATO",
    "YES", "KEY", "SET", "GET", "PUT", "END", "WOW", "LOL", "OMG",
    "THE", "FOR", "AND", "ARE", "WAS", "HAS", "ALL", "CAN", "MAY", "SHE", "HIM",
})

def _detect_ticker(query: str) -> Optional[str]:
    """Detect stock ticker in a query string. Returns ticker symbol or None."""
    # Explicit ticker prefix (e.g. "ticker AAPL" or "quote MSFT")
    # NOTE: "stock" is excluded here because it almost always follows the ticker symbol,
    # e.g. "AAPL stock" — pattern 3 handles that case correctly.
    m = re.search(r"(?:ticker|quote)\s+([A-Z]{1,5}(?:\.[A-Z]{2})?)\b", query, re.I)
    if m:
        return m.group(1).upper()

    # Pure ticker (1-5 uppercase letters)
    m = re.match(r"^([A-Z]{1,5}(?:\.[A-Z]{2})?)\s*$", query.strip())
    if m:
        symbol = m.group(1).upper()
        if symbol in _COMMON_TICKERS or any(symbol.endswith(s) for s in _EXCHANGE_SUFFIXES):
            return symbol
        if len(symbol) >= 2 and symbol not in _TICKER_STOPLIST:
            return symbol

    # Ticker in phrase
    m = re.search(r"\b([A-Z]{2,5})\s+(stock|price|share|quote|earnings|PE|market\s+cap|news|fundamental|chart|YTD)\b", query, re.I)
    if m:
        raw = m.group(1)
        # Only accept if the matched word is actually uppercase in the original query
        # (prevents false positives like "the market cap" matching "THE")
        if raw[0].isupper():
            symbol = raw.upper()
            if symbol not in _TICKER_STOPLIST:
                return symbol

    return None


def setup_search_routes(config) -> APIRouter:
    router = APIRouter(tags=["search"])

    @router.get("/api/search/config")
    async def get_search_settings() -> Dict[str, Any]:
        return get_search_config()

    @router.post("/api/search")
    async def do_web_search(request: Request) -> Dict[str, Any]:
        """Standalone web search — returns context string + source list.

        Used by Compare mode to pre-search once and share results across panes.
        """
        values = await _request_values(request)
        query = str(values.get("query") or values.get("q") or "").strip()
        if not query:
            return {"context": "", "sources": [], "error": "query is required"}
        time_filter = values.get("time_filter") or values.get("freshness")
        if time_filter is not None:
            time_filter = str(time_filter).strip() or None
        try:
            context, sources = comprehensive_web_search(
                query, return_sources=True, time_filter=time_filter,
            )
            return {"context": context, "sources": sources}
        except Exception as e:
            logger.error(f"Standalone web search failed: {e}")
            return {"context": "", "sources": [], "error": str(e)}

    @router.get("/api/search/providers")
    async def list_search_providers():
        """Return available search providers with config status."""
        providers = []
        for pid, (label, needs_key, needs_url) in PROVIDER_INFO.items():
            if pid == "disabled":
                continue
            available = True
            if needs_key and not _get_provider_key(pid):
                available = False
            if needs_url and pid == "searxng" and not _get_search_instance():
                available = False
            providers.append({
                "id": pid,
                "label": label,
                "available": available,
            })
        return providers

    @router.post("/api/search/query")
    async def search_with_provider(request: Request) -> Dict[str, Any]:
        """Search using a specific provider. Used by compare search mode."""
        values = await _request_values(request)
        query = str(values.get("query") or values.get("q") or "").strip()
        provider = str(values.get("provider") or "").strip()
        try:
            count = int(values.get("count") or values.get("limit") or 10)
        except Exception:
            count = 10
        if not query:
            return {"results": [], "provider": provider, "error": "query is required"}
        if provider not in PROVIDER_INFO or provider == "disabled":
            return {"results": [], "provider": provider, "error": "Unknown provider"}
        t0 = time.time()
        try:
            results = _call_provider(provider, query, min(count, 20))
            elapsed = round(time.time() - t0, 2)
            return {"results": results, "provider": provider, "time": elapsed}
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            logger.error(f"Search provider {provider} failed: {e}")
            return {"results": [], "provider": provider, "time": elapsed, "error": str(e)}

    # ── Global Search: Intent Classification ──

    @router.post("/api/search/intent")
    async def classify_search_intent(request: Request) -> Dict[str, Any]:
        """Classify a search query into an intent mode.
        
        Returns:
            mode: 'ticker' | 'web' | 'deep' | 'chat'
            confidence: 0.0 - 1.0
            ticker: detected ticker symbol (if mode='ticker')
            subMode: sub-classification for UI hints
        """
        values = await _request_values(request)
        query = str(values.get("query") or values.get("q") or "").strip()
        if not query:
            return {"mode": "chat", "confidence": 0.0, "ticker": None, "subMode": None}

        # ── Ticker detection ──
        ticker = _detect_ticker(query)
        if ticker:
            submode = "quote"
            if re.search(r"\b(chart|graph|performance|YTD|return)\b", query, re.I):
                submode = "chart"
            elif re.search(r"\b(fundamental|financial|income|balance|cash.flow|ratio)\b", query, re.I):
                submode = "fundamentals"
            elif re.search(r"\b(news|headline|latest)\b", query, re.I):
                submode = "news"
            return {
                "mode": "ticker",
                "confidence": 0.9,
                "ticker": ticker,
                "subMode": submode,
            }

        # ── Deep research patterns ──
        word_count = len(query.split())
        deep_score = 0.0

        deep_patterns = [
            r"^(analyze|research|investigate|study|examine|evaluate)\s",
            r"^(compare|contrast|differentiate)\s.*\s(vs|versus|and|with)\s",
            r"deep\s+(research|dive|analysis|investigation)",
            r"comprehensive\s+(analysis|report|research|review)",
            r"(competitive|competitor|market)\s+(analysis|landscape|position)",
            r"(SWOT|PESTEL|due.diligence|industry.analysis)",
            r"(multi.step|multi.round)\s+(research|analysis)",
            r"(quarterly|annual|fiscal)\s+(results|earnings|report)\s+(analysis|review)",
        ]
        for pat in deep_patterns:
            if re.search(pat, query, re.I):
                deep_score = max(deep_score, 0.85)
                break

        if word_count > 15:
            deep_score = max(deep_score, 0.55)
        if word_count > 25:
            deep_score = max(deep_score, 0.7)
        if re.search(r"\b(industry|sector|market.trend|economic|macro|fiscal|monetary|regulatory)\b", query, re.I) and word_count > 8:
            deep_score = max(deep_score, 0.65)
        if re.search(r"\b(and|or)\b.*\b(what|how|why|who|where)\b", query, re.I) and word_count > 10:
            deep_score = max(deep_score, 0.6)

        if deep_score >= 0.5:
            submode = "general"
            if re.search(r"\b(industry|sector|market)\b", query, re.I):
                submode = "industry"
            elif re.search(r"\b(company|competitor|competitive)\b", query, re.I):
                submode = "competitive"
            elif re.search(r"\b(economic|macro|fiscal|monetary|fed|central.bank)\b", query, re.I):
                submode = "macro"
            return {
                "mode": "deep",
                "confidence": round(deep_score, 2),
                "ticker": None,
                "subMode": submode,
            }

        # ── Web search patterns ──
        web_score = 0.0

        web_patterns = [
            r"^(search|find|look up|google|search.for)\s",
            r"news\s+(about|on|regarding|for)",
            r"latest\s+(news|updates|headlines)",
            r"(breaking|top.story)",
            r"^(weather|forecast|temperature|stock.price|market)\s",
            r"^(price|cost|rate|value)\s+of\s",
        ]
        for pat in web_patterns:
            if re.search(pat, query, re.I):
                web_score = max(web_score, 0.85)
                break

        if word_count <= 8 and re.search(r"\b(what|who|where|when|why|how)\b", query, re.I):
            web_score = max(web_score, 0.6)
        if re.search(r"\b(today|yesterday|this.(week|month|year|quarter)|latest|recent|current|breaking)\b", query, re.I):
            web_score = max(web_score, 0.7)

        if web_score >= 0.5:
            submode = "news" if re.search(r"\b(news|headline|latest|breaking|today)\b", query, re.I) else "general"
            return {
                "mode": "web",
                "confidence": round(web_score, 2),
                "ticker": None,
                "subMode": submode,
            }

        # ── Default: chat mode ──
        return {
            "mode": "chat",
            "confidence": 0.7 if word_count <= 12 else 0.4,
            "ticker": None,
            "subMode": None,
        }

    @router.get("/api/search/suggest")
    async def search_suggestions(
        q: str = Query("", description="Search query"),
        limit: int = Query(5, ge=1, le=20),
    ):
        """Get search suggestions for autocomplete."""
        if not q or len(q) < 2:
            return {"suggestions": []}

        # Try to get actual search suggestions from the configured provider
        try:
            context, sources = comprehensive_web_search(q, return_sources=True)
            suggestions = []
            for src in sources[:limit]:
                suggestions.append({
                    "title": src.get("title", ""),
                    "snippet": src.get("snippet", ""),
                    "url": src.get("url", ""),
                })
            return {"suggestions": suggestions}
        except Exception as e:
            logger.warning(f"Search suggestions failed (non-critical): {e}")
            return {"suggestions": []}

    @router.get("/api/search/ticker/{symbol}")
    async def ticker_lookup(symbol: str):
        """Look up a stock ticker symbol and return basic info.
        
        Returns market data if available, otherwise basic metadata.
        """
        if not symbol or not re.match(r"^[A-Z]{1,5}(\.[A-Z]{2})?$", symbol.upper()):
            return {"error": "Invalid ticker symbol", "symbol": symbol}

        symbol = symbol.upper()

        # Try to search for the ticker via web search
        try:
            query = f"{symbol} stock price market cap financial data"
            context, sources = comprehensive_web_search(query, return_sources=True)
            return {
                "symbol": symbol,
                "sources": sources[:5],
                "context": context[:2000] if context else "",
            }
        except Exception as e:
            logger.warning(f"Ticker lookup failed: {e}")
            return {
                "symbol": symbol,
                "sources": [],
                "context": "",
                "error": str(e),
            }

    return router
