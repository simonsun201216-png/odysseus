// static/js/intent.js
//
// Intent Recognition Engine — classifies search queries into modes:
//   ticker  → stock/instrument lookup (Bloomberg-style)
//   web     → traditional web search
//   deep    → multi-source deep research
//   chat    → direct AI response (default)

/**
 * Common US stock tickers (top 500+ by market cap + popular symbols).
 * Used for client-side ticker validation before hitting the API.
 * Covers: NYSE, NASDAQ, AMEX large/mid-cap + popular ETFs + crypto.
 */
const COMMON_TICKERS = new Set([
  // Mega-cap tech
  'AAPL','MSFT','GOOGL','GOOG','AMZN','NVDA','META','TSLA',
  // FAANG-adjacent
  'NFLX','ADBE','CRM','INTC','AMD','IBM','ORCL','CSCO','QCOM',
  // Tech
  'UBER','LYFT','SNAP','PINS','SPOT','RBLX','PLTR','SNOW','DDOG',
  'ZM','DOCU','SQ','SHOP','WDAY','NOW','PANW','FTNT','CRWD',
  'ZS','NET','OKTA','MDB','ESTC','MRNA','ABNB','DASH','WIX',
  // Mega-cap finance
  'JPM','BAC','WFC','C','GS','MS','BLK','SCHW','AXP','V','MA',
  // Insurance
  'BRK.A','BRK.B','MET','PRU','AIG','ALL','TRV','PGR','CB',
  // Healthcare
  'UNH','JNJ','PFE','ABBV','MRK','ABT','TMO','DHR','BMY','LLY',
  'AMGN','GILD','VRTX','REGN','ISRG','SYK','BSX','MDT','CI',
  'CVS','HUM','ANTM','CNC','MOH','ELV',
  // Consumer
  'WMT','COST','HD','LOW','TGT','DG','DLTR','SBUX','MCD','CMG',
  'YUM','DPZ','NKE','LULU','DIS','CMCSA','ROKU','WBD','PARA',
  // Energy
  'XOM','CVX','COP','SLB','EOG','PXD','OXY','MPC','PSX','VLO',
  // Industrials
  'CAT','DE','BA','LMT','GD','NOC','RTX','GE','HON','MMM',
  'UPS','FDX','CSX','UNP','NSC','ETN','ITW','CARR','HWM',
  // Telco/Media
  'T','VZ','TMUS','CHTR','CMCSA','FOXA','FOX','NWSA','NWS',
  // ETFs
  'SPY','QQQ','DIA','IWM','VTI','VOO','BND','TLT','GLD','SLV',
  'XLF','XLK','XLV','XLI','XLE','XLC','XLY','XLP','XLU','XLB',
  'VXUS','VEU','EEM','EFA','EWJ','FXI','ARKK','ARKW','ARKG',
  'IBIT','FBTC','BITO',
  // Crypto
  'BTC','ETH','SOL','XRP','ADA','DOT','AVAX','DOGE','LINK','MATIC',
  // China/HK
  'BABA','JD','PDD','BIDU','NIO','LI','XPEV','TCEHY',
  // Defense
  'GD','NOC','LMT','RTX','LHX','HII',
  // Other major
  'NEE','DUK','SO','D','AEP','SRE','PEG','ED','AWK',
  'CCI','EQIX','AMT','PLD','WELL','SPG','O','PSA','DLR',
  'WM','RSG','ECL','SHW','APD','LIN',
  // Canadian
  'SHOP.TO','RY','TD','ENB','CNQ','SU','TRP','BNS','BMO','CM',
]);

/** Patterns that strongly indicate a NEWS / WEB SEARCH intent */
const WEB_PATTERNS = [
  /^(search|find|look up|google|search for)\s/i,
  /news\s+(about|on|regarding|for)/i,
  /latest\s+(news|updates|headlines)/i,
  /what('s| is)\s+(the\s+)?(latest|recent|current|new)\s/i,
  /who\s+(won|is|are|was|were)\s/i,
  /^(top|trending|popular|viral)\s/i,
  /^(weather|forecast|temperature|stock price|market)\s/i,
  /^(price|cost|rate|value)\s+of\s/i,
  /^(how\s+much|how\s+many)\s+(is|are|does|did)\s/i,
  /^(where|when|why)\s+(is|are|was|were|did|does|do|can|will)\s/i,
  // News/current events
  /breaking\s/i,
  /^(elon|trump|biden|putin|xi|musk|bezos)/i,
];

/** Patterns that indicate DEEP RESEARCH intent */
const DEEP_PATTERNS = [
  /^(analyze|research|investigate|study|examine|evaluate)\s/i,
  /^(compare|contrast|differentiate)\s.*\s(vs|versus|and|with)\s/i,
  /deep\s+(research|dive|analysis|investigation)/i,
  /comprehensive\s+(analysis|report|research|review)/i,
  /^(what\s+is\s+the\s+(impact|effect|outlook|future|trend)\s+of)\s/i,
  /(competitive|competitor|market)\s+(analysis|landscape|position)/i,
  /(SWOT|PESTEL|five\s+forces)\s+(analysis|of)/i,
  /(due\s+diligence|industry\s+analysis|sector\s+(deep\s+)?dive)/i,
  /(multi-step|multi-round)\s+(research|analysis)/i,
  /^(write|generate|create|produce)\s+a\s+(detailed|comprehensive|full)\s+(report|analysis)/i,
  /(quarterly|annual|fiscal)\s+(results|earnings|report|performance)\s+(analysis|review)/i,
  /\b(over\s+the\s+(next|coming|past)\s+\d+\s+(year|month|quarter)s?)\b/i,
];

/** Patterns that strongly indicate TICKER intent */
const TICKER_PATTERNS = [
  /^(stock|ticker|quote)\s+[A-Z]{1,5}\b/i,
  /\b[A-Z]{2,5}\s+(stock|price|quote|share|fundamental|financial|news|chart|YTD)s?\b/i,
  /^(price|chart|performance)\s+of\s+[A-Z]{1,5}\b/i,
];

/**
 * Known exchange suffixes for international tickers.
 */
const EXCHANGE_SUFFIXES = [
  '.TO', '.V', '.L', '.DE', '.PA', '.MI', '.AS', '.BR',
  '.HK', '.T', '.KS', '.SS', '.SZ', '.AX', '.NZ', '.SI',
  '.ST', '.CO', '.OL', '.HE', '.IR', '.PL', '.VI', '.AT',
];

/** Stoplist: common uppercase words that should NOT be treated as tickers */
const TICKER_STOPLIST = new Set([
  'AI', 'IT', 'OK', 'GO', 'NO', 'TO', 'BY', 'AT', 'IN', 'IS', 'IT', 'ON',
  'UP', 'WE', 'US', 'MY', 'ME', 'TV', 'CD', 'DVD', 'CEO', 'CTO', 'CFO',
  'COO', 'USA', 'UK', 'EU', 'UN', 'GDP', 'IPO', 'ETF', 'REIT',
  'ROI', 'EPS', 'PE', 'API', 'HTML', 'CSS', 'JS', 'TS',
  'SELL', 'BUY', 'HOLD', 'TOP', 'NEWS', 'BIG', 'NEW', 'OLD', 'HOT',
  'FED', 'SEC', 'IRS', 'FDIC', 'WTO', 'IMF', 'WHO', 'NATO',
  'YES', 'KEY', 'SET', 'GET', 'PUT', 'END', 'WOW', 'LOL', 'OMG',
]);

/**
 * Detect if a string looks like a stock ticker.
 * Returns the ticker symbol or null.
 */
function detectTicker(query) {
  // Explicit ticker prefix
  const tickerMatch = query.match(/^(?:ticker|stock|quote)\s+([A-Z]{1,5})(?:\.[A-Z]{2})?\b/i);
  if (tickerMatch) {
    const symbol = tickerMatch[1].toUpperCase();
    if (!TICKER_STOPLIST.has(symbol)) return symbol;
  }

  // Pure ticker (1-5 uppercase letters, optionally matching known tickers)
  const pureMatch = query.match(/^([A-Z]{1,5}(?:\.[A-Z]{2})?)\s*$/);
  if (pureMatch) {
    const symbol = pureMatch[1].toUpperCase();
    // Check if it's in our known tickers or has exchange suffix
    if (COMMON_TICKERS.has(symbol) || EXCHANGE_SUFFIXES.some(s => symbol.endsWith(s))) {
      return symbol;
    }
    // Single-letter tickers are often not tickers
    if (symbol.length >= 2 && !TICKER_STOPLIST.has(symbol)) {
      // Loose match - accept if reasonably ticker-like (this will be validated server-side)
      return symbol;
    }
  }

  // Ticker in a phrase: "AAPL stock price" or "NVDA news"
  const phraseMatch = query.match(/\b([A-Z]{2,5})\s+(stock|price|share|quote|earnings|PE|market\s+cap|news|fundamental|chart|YTD)\b/i);
  if (phraseMatch) {
    const symbol = phraseMatch[1].toUpperCase();
    if (!TICKER_STOPLIST.has(symbol)) return symbol;
  }

  return null;
}

/**
 * Classify a search query into intent modes.
 * Returns { mode, confidence, ticker, subMode }
 *
 * Modes:
 *   ticker  → stock/instrument lookup
 *   web     → traditional web search
 *   deep    → multi-source deep research
 *   chat    → direct AI response (default)
 *
 * Confidence: 0.0 - 1.0
 */
function detectIntent(query) {
  if (!query || !query.trim()) {
    return { mode: 'chat', confidence: 0, ticker: null, subMode: null };
  }

  const trimmed = query.trim();
  const q = trimmed;

  // Check for explicit mode prefix commands
  if (/^\/web\b/i.test(q)) {
    return { mode: 'web', confidence: 1.0, ticker: null, subMode: null, cleanQuery: q.replace(/^\/web\s*/i, '') };
  }
  if (/^\/research\b/i.test(q)) {
    return { mode: 'deep', confidence: 1.0, ticker: null, subMode: null, cleanQuery: q.replace(/^\/research\s*/i, '') };
  }
  if (/^\/ticker\b/i.test(q)) {
    const ticker = detectTicker(q.replace(/^\/ticker\s*/i, ''));
    return { mode: 'ticker', confidence: 1.0, ticker, subMode: null, cleanQuery: q.replace(/^\/ticker\s*/i, '') };
  }
  if (/^\/ai\b/i.test(q)) {
    return { mode: 'chat', confidence: 1.0, ticker: null, subMode: null, cleanQuery: q.replace(/^\/ai\s*/i, '') };
  }
  if (/^\/chat\b/i.test(q)) {
    return { mode: 'chat', confidence: 1.0, ticker: null, subMode: null, cleanQuery: q.replace(/^\/chat\s*/i, '') };
  }

  // Score-based intent detection
  let scores = { ticker: 0, web: 0, deep: 0, chat: 0.1 }; // chat is default low baseline

  // 1. Ticker detection
  const ticker = detectTicker(q);
  if (ticker) {
    // If it's purely a ticker (no other context), strong ticker signal
    if (/^[A-Z]{1,5}(?:\.[A-Z]{2})?\s*$/.test(q)) {
      scores.ticker = 0.95;
    } else {
      // Ticker mentioned in context
      scores.ticker = 0.7;
    }

    // Check for financial-specific keywords that strengthen ticker intent
    if (/\b(price|stock|share|PE|ratio|market\s+cap|dividend|yield|EPS|revenue|profit|balance|income|cash\s+flow)\b/i.test(q)) {
      scores.ticker = Math.max(scores.ticker, 0.85);
    }

    // News about a specific ticker
    if (/\b(news|headline|latest|update)\b/i.test(q)) {
      scores.ticker = Math.max(scores.ticker, 0.8);
    }

    // If asking for chart
    if (/\b(chart|graph|performance|return|YTD|MTD)\b/i.test(q)) {
      scores.ticker = Math.max(scores.ticker, 0.9);
    }
  }

  // 2. Web search detection
  for (const pattern of WEB_PATTERNS) {
    if (pattern.test(q)) {
      scores.web = Math.max(scores.web, 0.85);
      break;
    }
  }

  // Shorter queries asking for current info → web search
  if (q.split(/\s+/).length <= 8 && /\b(what|who|where|when|why|how)\b/i.test(q)) {
    scores.web = Math.max(scores.web, 0.6);
  }

  // Time-sensitive queries → web search
  if (/\b(today|yesterday|this\s+(week|month|year|quarter)|latest|recent|current|breaking|now)\b/i.test(q)) {
    scores.web = Math.max(scores.web, 0.7);
  }

  // 3. Deep research detection
  for (const pattern of DEEP_PATTERNS) {
    if (pattern.test(q)) {
      scores.deep = Math.max(scores.deep, 0.85);
      break;
    }
  }

  // Long, complex queries → deep research
  const wordCount = q.split(/\s+/).length;
  if (wordCount > 15 && scores.web < 0.8) {
    scores.deep = Math.max(scores.deep, 0.55);
  }
  if (wordCount > 25) {
    scores.deep = Math.max(scores.deep, 0.7);
  }

  // Multi-part questions (contains "and" / "or" connecting clauses)
  if (/\b(and|or)\b.*\b(what|how|why|who|where)\b/i.test(q) && wordCount > 10) {
    scores.deep = Math.max(scores.deep, 0.6);
  }

  // Financial/industry analysis keywords
  if (/\b(industry|sector|market\s+trend|economic|macro|fiscal|monetary|regulatory)\b/i.test(q) && wordCount > 8) {
    scores.deep = Math.max(scores.deep, 0.65);
  }

  // 4. Chat detection (default)
  // Simple, direct questions are chat
  if (wordCount <= 12 && /\b(explain|what is|what are|how do|how does|how can|define|tell me|meaning of|difference between)\b/i.test(q)) {
    scores.chat = Math.max(scores.chat, 0.65);
  }

  // Greetings and simple interaction
  if (wordCount <= 6 && /\b(hello|hi|hey|thanks|help|yes|no|okay|ok)\b/i.test(q)) {
    scores.chat = Math.max(scores.chat, 0.9);
  }

  // Technical questions that need explanation
  if (/\b(how\s+(does|do|can|would|will|should)|why\s+(does|do|is|are|would|did)|what\s+((does|is|are|would)\s+)?the\s+(difference|purpose|meaning|benefit|advantage|disadvantage))\b/i.test(q) && wordCount <= 20) {
    scores.chat = Math.max(scores.chat, 0.6);
  }

  // Pick the mode with the highest score
  let bestMode = 'chat';
  let bestScore = scores.chat;

  if (scores.ticker > bestScore && scores.ticker >= 0.6) {
    bestMode = 'ticker';
    bestScore = scores.ticker;
  }
  if (scores.web > bestScore && scores.web >= 0.5) {
    bestMode = 'web';
    bestScore = scores.web;
  }
  if (scores.deep > bestScore && scores.deep >= 0.5) {
    bestMode = 'deep';
    bestScore = scores.deep;
  }

  // Sub-mode classification for UI hints
  let subMode = null;
  if (bestMode === 'ticker') {
    if (/\b(chart|graph|performance|YTD|return)\b/i.test(q)) subMode = 'chart';
    else if (/\b(fundamental|financial|income|balance|cash\s+flow|ratio)\b/i.test(q)) subMode = 'fundamentals';
    else if (/\b(news|headline|latest)\b/i.test(q)) subMode = 'news';
    else subMode = 'quote';
  } else if (bestMode === 'web') {
    if (/\b(news|headline|latest|breaking|today)\b/i.test(q)) subMode = 'news';
    else subMode = 'general';
  } else if (bestMode === 'deep') {
    if (/\b(industry|sector|market)\b/i.test(q)) subMode = 'industry';
    else if (/\b(company|competitor|competitive)\b/i.test(q)) subMode = 'competitive';
    else if (/\b(economic|macro|fiscal|monetary|fed|central\s+bank)\b/i.test(q)) subMode = 'macro';
    else subMode = 'general';
  }

  return {
    mode: bestMode,
    confidence: Math.round(bestScore * 100) / 100,
    ticker: bestMode === 'ticker' ? ticker : null,
    subMode,
    scores,
    wordCount,
  };
}

/**
 * Get a human-readable label for a mode.
 */
function getModeLabel(mode) {
  const labels = {
    ticker: 'Stock Quote',
    web: 'Web Search',
    deep: 'Deep Research',
    chat: 'AI Chat',
  };
  return labels[mode] || 'AI Chat';
}

/**
 * Get a mode icon SVG
 */
function getModeIcon(mode) {
  const icons = {
    ticker: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    web: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    deep: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>',
    chat: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  };
  return icons[mode] || icons.chat;
}

const intentModule = {
  detectIntent,
  detectTicker,
  getModeLabel,
  getModeIcon,
  COMMON_TICKERS,
};

export default intentModule;
export {
  detectIntent,
  detectTicker,
  getModeLabel,
  getModeIcon,
};
