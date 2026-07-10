// static/js/kbPanel.js
// KB Research panel — sidebar tool for browsing and searching the knowledge base

import uiModule from './ui.js';
import { showMeetingFromSource } from './meetingDetail.js';

let _modalEl = null;
let _closeHandler = null;

// ── API calls ────────────────────────────────────────────────────────────────

async function kbSearch(query, mode, k) {
  const r = await fetch('/api/kb/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ query: query || '', mode: mode || 'scan', k: k || 10, min_score: 0.0 }),
  });
  if (!r.ok) throw new Error('KB search failed');
  return r.json();
}

// ── Panel render ─────────────────────────────────────────────────────────────

function renderKbPanel() {
  closeKbPanel();

  var esc = uiModule.esc;

  var panelHtml = ''
    + '<div id="kb-panel-modal" class="modal kb-panel-modal">'
    + '<div class="modal-content kb-panel-content" role="dialog" aria-label="Knowledge Base">'
    + '<div class="modal-header kb-panel-header">'
    + '<h4 style="margin:0;display:flex;align-items:center;gap:6px;">'
    + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>'
    + 'KB Research</h4>'
    + '<button class="close-btn kb-panel-close-btn" id="kb-panel-close" aria-label="Close">&#x2716;</button>'
    + '</div>'
    + '<div class="kb-panel-search">'
    + '<input type="text" id="kb-panel-input" placeholder="Search meetings, companies, topics..." class="kb-panel-input" />'
    + '<button id="kb-panel-go-btn" class="kb-panel-go-btn">Search</button>'
    + '</div>'
    + '<div class="kb-panel-body" id="kb-panel-body">'
    + '<div class="kb-panel-welcome" id="kb-panel-welcome">'
    + '<div class="kb-welcome-hint">Search the Prophetis meeting database.</div>'
    + '<div class="kb-quick-links">'
    + '<button class="kb-quick-btn" data-q="AI">AI</button>'
    + '<button class="kb-quick-btn" data-q="半导体">芯片</button>'
    + '<button class="kb-quick-btn" data-q="新能源">新能源</button>'
    + '<button class="kb-quick-btn" data-q="汽车">汽车</button>'
    + '<button class="kb-quick-btn" data-q="消费">消费</button>'
    + '<button class="kb-quick-btn" data-q="医药">医药</button>'
    + '</div></div>'
    + '<div id="kb-panel-results" class="kb-panel-results hidden"></div>'
    + '</div></div></div>';

  var wrapper = document.createElement('div');
  wrapper.innerHTML = panelHtml;
  _modalEl = wrapper.firstElementChild;
  document.body.appendChild(_modalEl);
  _modalEl.classList.remove('hidden');

  // Wire close
  var closeBtn = _modalEl.querySelector('#kb-panel-close');
  if (closeBtn) closeBtn.onclick = closeKbPanel;
  _modalEl.onclick = function(e) { if (e.target === _modalEl) closeKbPanel(); };

  // Wire search
  var input = _modalEl.querySelector('#kb-panel-input');
  var goBtn = _modalEl.querySelector('#kb-panel-go-btn');
  function doSearch() {
    var q = (input.value || '').trim();
    if (!q) return;
    performSearch(q);
  }
  goBtn.onclick = doSearch;
  input.onkeydown = function(e) { if (e.key === 'Enter') doSearch(); };

  // Wire quick links
  _modalEl.querySelectorAll('.kb-quick-btn').forEach(function(btn) {
    btn.onclick = function() { input.value = btn.dataset.q; doSearch(); };
  });

  // ESC
  import('./escMenuStack.js').then(function(mod) {
    _closeHandler = mod.bindMenuDismiss(_modalEl, closeKbPanel);
  }).catch(function(){});

  setTimeout(function() { input.focus(); }, 100);
}

async function performSearch(query) {
  var resultsEl = document.getElementById('kb-panel-results');
  var welcomeEl = document.getElementById('kb-panel-welcome');
  if (!resultsEl || !welcomeEl) return;

  welcomeEl.classList.add('hidden');
  resultsEl.classList.remove('hidden');
  resultsEl.innerHTML = '<div class="kb-loading">Searching...</div>';

  try {
    var data = await kbSearch(query, 'scan', 15);
    var r = data && data.results ? data.results : [];

    if (!r.length) {
      resultsEl.innerHTML = '<div class="kb-empty">No results found.</div>';
      return;
    }

    var esc = uiModule.esc;
    var html = '<div class="kb-result-count">' + r.length + ' results for "<strong>' + esc(query) + '</strong>"</div>';

    var kw = r.filter(function(x) { return x.match_type === 'keyword_match'; });
    var sd = r.filter(function(x) { return x.match_type === 'semantic_discovery'; });

    if (kw.length) {
      html += '<div class="kb-result-group"><span class="kb-group-label">Keyword match (' + kw.length + ')</span></div>';
      html += renderResultList(kw);
    }
    if (sd.length) {
      html += '<div class="kb-result-group" style="margin-top:8px;"><span class="kb-group-label">Semantic discovery (' + sd.length + ')</span></div>';
      html += renderResultList(sd);
    }
    resultsEl.innerHTML = html;
  } catch (err) {
    resultsEl.innerHTML = '<div class="kb-error">Error: ' + esc(err.message) + '</div>';
  }
}

function renderResultList(results) {
  var esc = uiModule.esc;
  var html = '<div class="kb-results-list">';
  for (var i = 0; i < results.length; i++) {
    var r = results[i];
    html += '<div class="kb-result-item" data-source-id="' + esc(r.source_id) + '">'
      + '<div class="kb-result-header">'
      + '<span class="kb-result-company">' + esc(r.company || '--') + '</span>'
      + '<span class="kb-result-date">' + esc(r.meeting_date || '') + '</span>'
      + '<span class="kb-result-tag">' + esc(r.source_tag || '') + '</span>'
      + '</div>'
      + '<div class="kb-result-summary">' + esc((r.core_summary || '').slice(0, 200)) + '</div>'
      + '<div class="kb-result-footer">'
      + '<span class="kb-result-source">' + esc(r.source_id) + '</span>'
      + '<span class="kb-result-open">View</span>'
      + '</div></div>';
  }
  html += '</div>';
  return html;
}

// ── Open / Close ─────────────────────────────────────────────────────────────

export function openKbPanel() {
  renderKbPanel();
}

export function closeKbPanel() {
  if (_closeHandler && typeof _closeHandler === 'function') {
    try { _closeHandler(); } catch (_) {}
    _closeHandler = null;
  }
  if (_modalEl) { _modalEl.remove(); _modalEl = null; }
}

// ── Init (called from app.js) ────────────────────────────────────────────────

export function initKbPanel() {
  // Direct event binding for sidebar and rail buttons (more reliable than onclick=)
  var sidebarBtn = document.getElementById('tool-kb-btn');
  if (sidebarBtn) {
    sidebarBtn.addEventListener('click', function(e) {
      e.preventDefault();
      openKbPanel();
    });
  }
  var railBtn = document.getElementById('rail-kb');
  if (railBtn) {
    railBtn.addEventListener('click', function(e) {
      e.preventDefault();
      openKbPanel();
    });
  }

  // Result click delegation (panel item -> meeting detail)
  document.addEventListener('click', function(e) {
    var item = e.target.closest('.kb-result-item');
    if (item && item.closest('#kb-panel-modal')) {
      var sid = item.dataset.sourceId;
      if (sid) showMeetingFromSource(sid);
    }
  });
}
