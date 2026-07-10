// static/js/global-search.js
//
// Global Unified Search — Ctrl+K / Cmd+K overlay with intent detection.
// Provides: Web Search, AI Chat, Deep Research, Ticker/Stock lookup.
//
// Architecture:
//   global-search.js  (this file)        → UI overlay, mode routing
//   intent.js                             → query classification
//   /api/search/intent                    → server-side intent classification
//   /api/search                           → web search
//   /api/chat_stream                      → AI chat + research
//   /api/research/*                       → deep research
//   /api/search/ticker/{symbol}           → ticker data

import intentModule from './intent.js';
import chatModule from './chat.js';
import sessionModule from './sessions.js';
import uiModule from './ui.js';
import Storage from './storage.js';

const { detectIntent, getModeLabel, getModeIcon } = intentModule;

let API_BASE = '';
let _isOpen = false;
let _debounceTimer = null;
let _selectedIndex = -1;
let _results = [];
let _currentIntent = null;
let _overrideMode = null; // User-overridden mode
let _recentSearches = [];

function el(id) { return document.getElementById(id); }

// ── Mode tab definitions ──
const MODE_TABS = [
  { id: 'auto', label: 'Auto', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>' },
  { id: 'ticker', label: 'Ticker', icon: getModeIcon('ticker') },
  { id: 'web', label: 'Web', icon: getModeIcon('web') },
  { id: 'deep', label: 'Research', icon: getModeIcon('deep') },
  { id: 'chat', label: 'Chat', icon: getModeIcon('chat') },
];

// ── Public API ──

export function openSearch() {
  const overlay = el('global-search-overlay');
  if (!overlay) return;
  overlay.classList.remove('hidden');
  const input = el('global-search-input');
  if (input) {
    input.value = '';
    input.focus();
    _updatePlaceholder();
  }
  _selectedIndex = -1;
  _results = [];
  _currentIntent = null;
  _overrideMode = null;
  _renderResults([]);
  _updateModeIndicator();
  _loadRecentSearches();
  _isOpen = true;
  document.body.classList.add('global-search-open');
}

export function closeSearch() {
  const overlay = el('global-search-overlay');
  if (!overlay) return;
  overlay.classList.add('hidden');
  _isOpen = false;
  _selectedIndex = -1;
  _results = [];
  _currentIntent = null;
  _overrideMode = null;
  document.body.classList.remove('global-search-open');
}

export function isOpen() {
  return _isOpen;
}

export function toggle() {
  if (_isOpen) closeSearch();
  else openSearch();
}

// ── Initialization ──

export function init(apiBase) {
  API_BASE = apiBase || '';

  const input = el('global-search-input');
  if (input) {
    input.addEventListener('input', _handleInput);
    input.addEventListener('keydown', _handleKeydown);
    input.addEventListener('focus', () => { if (!input.value) _loadRecentSearches(); });
  }

  // Close on overlay click (not popup click)
  const overlay = el('global-search-overlay');
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeSearch();
    });
  }

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _isOpen) {
      closeSearch();
      e.preventDefault();
    }
    // Cmd+K / Ctrl+K to open
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      toggle();
    }
    // Slash to open (when not typing in an input)
    if (e.key === '/' && !_isOpen && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tag = document.activeElement?.tagName;
      if (tag !== 'INPUT' && tag !== 'TEXTAREA' && !document.activeElement?.isContentEditable) {
        e.preventDefault();
        openSearch();
      }
    }
  });

  // Mode tab click handlers
  MODE_TABS.forEach(tab => {
    const btn = el(`gs-mode-${tab.id}`);
    if (btn) {
      btn.addEventListener('click', () => {
        _overrideMode = tab.id === 'auto' ? null : tab.id;
        _updateModeIndicator();
        if (el('global-search-input')?.value?.trim()) {
          _executeSearch(el('global-search-input').value.trim());
        }
      });
    }
  });

  // Quick action buttons
  const actionMap = {
    'gs-action-web': 'web',
    'gs-action-research': 'deep',
    'gs-action-chat': 'chat',
    'gs-action-ticker': 'ticker',
  };
  Object.entries(actionMap).forEach(([btnId, mode]) => {
    const btn = el(btnId);
    if (btn) {
      btn.addEventListener('click', () => {
        _overrideMode = mode;
        _updateModeIndicator();
        const input = el('global-search-input');
        if (input) {
          input.placeholder = _getPlaceholderForMode(mode);
          input.focus();
        }
        _renderResults([]);
        _renderQuickActions(false);
      });
    }
  });

  // Submit button
  const submitBtn = el('global-search-submit');
  if (submitBtn) {
    submitBtn.addEventListener('click', () => {
      const input = el('global-search-input');
      if (input?.value?.trim()) _executeSearch(input.value.trim());
    });
  }
}

// ── Internal ──

function _getPlaceholderForMode(mode) {
  const placeholders = {
    ticker: 'Search ticker (e.g. AAPL, MSFT, TSLA)...',
    web: 'Search the web...',
    deep: 'What would you like to research deeply?',
    chat: 'Ask Prophetis anything...',
  };
  return placeholders[mode] || 'Search anything...';
}

function _updatePlaceholder() {
  const input = el('global-search-input');
  if (!input) return;
  const mode = _overrideMode || (_currentIntent?.mode) || 'chat';
  input.placeholder = _getPlaceholderForMode(mode);
}

function _updateModeIndicator() {
  const mode = _overrideMode || (_currentIntent?.mode) || 'chat';
  const activeMode = _overrideMode ? _overrideMode : (_currentIntent?.mode === 'ticker' ? 'ticker' : 'auto');

  // Update tabs
  MODE_TABS.forEach(tab => {
    const btn = el(`gs-mode-${tab.id}`);
    if (!btn) return;
    const isActive = tab.id === activeMode;
    btn.classList.toggle('active', isActive);
    if (isActive && !_overrideMode && _currentIntent) {
      btn.title = `Detected: ${getModeLabel(_currentIntent.mode)} (${Math.round(_currentIntent.confidence * 100)}%)`;
    } else {
      btn.title = tab.label;
    }
  });

  // Update detected mode badge
  const badge = el('gs-detected-mode');
  if (badge && _currentIntent && !_overrideMode) {
    badge.style.display = '';
    const confidence = Math.round(_currentIntent.confidence * 100);
    badge.innerHTML = `${getModeIcon(_currentIntent.mode)} ${getModeLabel(_currentIntent.mode)} ${confidence}%`;
    badge.className = 'gs-detected-mode gs-mode-' + _currentIntent.mode;
  } else if (badge) {
    badge.style.display = 'none';
  }

  // Update submit button text
  const submitBtn = el('global-search-submit');
  if (submitBtn) {
    const finalMode = _overrideMode || (_currentIntent?.mode) || 'chat';
    const labels = {
      ticker: 'View Stock',
      web: 'Search Web',
      deep: 'Deep Research',
      chat: 'Ask AI',
    };
    submitBtn.innerHTML = `${getModeIcon(finalMode)} ${labels[finalMode] || 'Search'}`;
  }

  _updatePlaceholder();
}

function _loadRecentSearches() {
  try {
    const stored = localStorage.getItem('global-search-recent');
    _recentSearches = stored ? JSON.parse(stored) : [];
  } catch { _recentSearches = []; }
}

function _saveRecentSearch(query) {
  try {
    _recentSearches = [query, ..._recentSearches.filter(s => s !== query)].slice(0, 10);
    localStorage.setItem('global-search-recent', JSON.stringify(_recentSearches));
  } catch {}
}

function _handleInput(e) {
  const query = e.target.value.trim();
  if (_debounceTimer) clearTimeout(_debounceTimer);

  if (!query) {
    _currentIntent = null;
    _updateModeIndicator();
    _renderResults([]);
    _renderQuickActions(true);
    return;
  }

  // Classify intent on every keystroke (fast, client-side)
  _currentIntent = detectIntent(query);
  _updateModeIndicator();

  _debounceTimer = setTimeout(async () => {
    await _fetchSuggestions(query);
  }, 200);
}

async function _fetchSuggestions(query) {
  if (!query) return;

  const mode = _overrideMode || _currentIntent?.mode || 'chat';

  try {
    let results = [];

    if (mode === 'ticker') {
      // Show ticker suggestions
      const ticker = intentModule.detectTicker(query);
      if (ticker) {
        results = [{
          type: 'ticker',
          symbol: ticker,
          title: ticker,
          subtitle: 'View stock quote & data',
          action: 'openTicker',
        }];
      }
    } else if (mode === 'web') {
      // Fetch web search suggestions
      try {
        const res = await fetch(`${API_BASE}/api/search/suggest?q=${encodeURIComponent(query)}&limit=5`);
        if (res.ok) {
          const data = await res.json();
          results = (data.suggestions || data.results || []).slice(0, 5).map(s => ({
            type: 'web',
            title: typeof s === 'string' ? s : (s.title || s.snippet || ''),
            subtitle: typeof s === 'string' ? '' : (s.snippet || s.url || ''),
            url: s.url,
            action: 'webSearch',
          }));
        }
      } catch {}

      // Fallback suggestions
      if (results.length === 0) {
        results = [{
          type: 'web',
          title: `Search web for "${query}"`,
          subtitle: 'Powered by ' + (window.searchModule?.getProviderLabel?.() || 'SearXNG'),
          action: 'webSearch',
        }];
      }
    } else if (mode === 'deep') {
      results = [{
        type: 'deep',
        title: `Deep research: "${query}"`,
        subtitle: 'Multi-source analysis with source gathering',
        action: 'deepResearch',
      }];
    } else {
      // Chat mode - show as AI query
      results = [{
        type: 'chat',
        title: query.length > 60 ? query.slice(0, 60) + '...' : query,
        subtitle: 'Ask Prophetis AI',
        action: 'chatQuery',
      }];
    }

    _results = results;
    _renderResults(results);
    _selectedIndex = -1;
  } catch (err) {
    console.error('Global search error:', err);
  }
}

function _executeSearch(query) {
  if (!query) return;

  _saveRecentSearch(query);

  const mode = _overrideMode || _currentIntent?.mode || 'chat';

  closeSearch();

  // Route to appropriate handler based on mode
  switch (mode) {
    case 'ticker': {
      const ticker = intentModule.detectTicker(query) || query.replace(/^\/ticker\s*/i, '').trim().toUpperCase();
      _routeTicker(ticker);
      break;
    }
    case 'web':
      _routeWebSearch(query);
      break;
    case 'deep':
      _routeDeepResearch(query);
      break;
    case 'chat':
    default:
      _routeChatQuery(query);
      break;
  }
}

function _routeTicker(symbol) {
  if (!symbol) return;

  // Open research panel with ticker query
  const msg = `Show me detailed information about ticker ${symbol}. Include current price, market cap, PE ratio, 52-week range, dividend yield, and key financial metrics.`;

  // Send message to chat
  _sendChatMessage(msg);

  // Also try to open ticker-specific research
  try {
    fetch(`${API_BASE}/api/research/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: `Research ticker ${symbol}`,
        mode: 'ticker',
        sources: ['web', 'financial'],
      }),
    }).catch(() => {});
  } catch {}
}

function _routeWebSearch(query) {
  // Enable web search toggle and send as chat message
  const webToggle = el('web-toggle');
  if (webToggle) webToggle.checked = true;

  _sendChatMessage(query);
}

function _routeDeepResearch(query) {
  // Enable research toggle and send
  const researchToggle = el('research-toggle');
  if (researchToggle) researchToggle.checked = true;

  // Sync the research indicator
  if (window._syncResearchIndicator) {
    window._syncResearchIndicator(true);
  }

  _sendChatMessage(query);
}

function _routeChatQuery(query) {
  _sendChatMessage(query);
}

function _sendChatMessage(msg) {
  // Set the message in the input and submit
  const messageInput = el('message');
  if (!messageInput) return;

  messageInput.value = msg;
  if (uiModule.autoResize) uiModule.autoResize(messageInput);

  // Click the send button
  const submitBtn = document.querySelector('.send-btn');
  if (submitBtn) {
    setTimeout(() => submitBtn.click(), 50);
  } else {
    // Fallback: submit the form
    const form = document.getElementById('chat-form');
    if (form) form.dispatchEvent(new Event('submit'));
  }
}

function _renderResults(results) {
  const container = el('global-search-results');
  if (!container) return;

  if (!results || results.length === 0) {
    container.innerHTML = '';
    container.classList.add('gs-results-empty');
    return;
  }

  container.classList.remove('gs-results-empty');

  let html = '';
  results.forEach((item, idx) => {
    const icon = _getResultIcon(item);
    const isSelected = idx === _selectedIndex;

    html += `<div class="gs-result-item ${isSelected ? 'selected' : ''}" data-index="${idx}" data-action="${item.action}" data-symbol="${item.symbol || ''}" data-url="${item.url || ''}">
      <div class="gs-result-icon">${icon}</div>
      <div class="gs-result-content">
        <div class="gs-result-title">${_escapeHtml(item.title)}</div>
        ${item.subtitle ? `<div class="gs-result-subtitle">${_escapeHtml(item.subtitle)}</div>` : ''}
      </div>
      ${item.action === 'openTicker' ? '<div class="gs-result-badge ticker">Stock</div>' : ''}
      ${item.action === 'webSearch' ? '<div class="gs-result-badge web">Web</div>' : ''}
      ${item.action === 'deepResearch' ? '<div class="gs-result-badge deep">Research</div>' : ''}
      ${item.action === 'chatQuery' ? '<div class="gs-result-badge chat">AI</div>' : ''}
    </div>`;
  });

  container.innerHTML = html;

  // Click handlers
  container.querySelectorAll('.gs-result-item').forEach(item => {
    item.addEventListener('click', () => {
      const input = el('global-search-input');
      if (input && input.value.trim()) _executeSearch(input.value.trim());
    });
  });
}

function _renderQuickActions(show) {
  const container = el('gs-quick-actions');
  if (!container) return;
  container.classList.toggle('hidden', !show);
}

function _getResultIcon(item) {
  const icons = {
    ticker: getModeIcon('ticker'),
    web: getModeIcon('web'),
    deep: getModeIcon('deep'),
    chat: getModeIcon('chat'),
  };
  return icons[item.type] || getModeIcon('chat');
}

function _handleKeydown(e) {
  const container = el('global-search-results');
  const items = container ? container.querySelectorAll('.gs-result-item') : [];
  const count = items.length;

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _selectedIndex = count > 0 ? Math.min(_selectedIndex + 1, count - 1) : -1;
    _updateSelection(items);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    _selectedIndex = _selectedIndex <= 0 ? (count > 0 ? count - 1 : -1) : _selectedIndex - 1;
    _updateSelection(items);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    const input = el('global-search-input');
    if (input?.value?.trim()) _executeSearch(input.value.trim());
  } else if (e.key === 'Tab') {
    // Tab between mode tabs
    e.preventDefault();
    _cycleMode();
  }
}

function _updateSelection(items) {
  items.forEach((item, i) => {
    item.classList.toggle('selected', i === _selectedIndex);
  });
  if (_selectedIndex >= 0 && items[_selectedIndex]) {
    items[_selectedIndex].scrollIntoView({ block: 'nearest' });
  }
}

function _cycleMode() {
  const modes = ['auto', 'ticker', 'web', 'deep', 'chat'];
  const current = _overrideMode || 'auto';
  const idx = modes.indexOf(current);
  const next = modes[(idx + 1) % modes.length];
  _overrideMode = next === 'auto' ? null : next;
  _updateModeIndicator();

  const input = el('global-search-input');
  if (input?.value?.trim()) _fetchSuggestions(input.value.trim());
}

function _escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

const globalSearchModule = {
  init,
  openSearch,
  closeSearch,
  toggle,
  isOpen,
};

export default globalSearchModule;
