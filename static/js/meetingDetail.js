// static/js/meetingDetail.js
// Meeting detail modal for Odysseus — KB source citations become clickable
// with an embedded view of the full meeting record (no page navigation).

import uiModule from './ui.js';
import markdownModule from './markdown.js';
import { bindMenuDismiss } from './escMenuStack.js';
import spinnerModule from './spinner.js';

let _modalEl = null;
let _closeHandler = null;

// ── API ──────────────────────────────────────────────────────────────────────

async function fetchMeetingBySource(sourceId) {
  const r = await fetch(`/api/kb/source/${encodeURIComponent(sourceId)}`, {
    credentials: 'same-origin',
  });
  if (!r.ok) throw new Error(`Source lookup failed: ${r.status}`);
  return r.json();
}

async function fetchMeetingByUid(uid) {
  const r = await fetch(`/api/v1/meetings/${encodeURIComponent(uid)}`, {
    credentials: 'same-origin',
  });
  if (!r.ok) throw new Error(`Meeting lookup failed: ${r.status}`);
  return r.json();
}

// ── Modal render ─────────────────────────────────────────────────────────────

function renderMeetingModal(data) {
  closeMeetingModal();

  const esc = uiModule.esc;

  // Normalise field names (kb source endpoint returns db column names)
  const company = data.company || data.company_name || '—';
  const meetingDate = data.meeting_date || '—';
  const industry = data.industry || '';
  const sourceTag = data.source_tag || data.source || '';
  const sentiment = data.sentiment || data.sentiment_raw || '';
  const sentimentVal = data.sentiment_val ?? null;
  const keywords = data.keywords || data.keywords_clean || '';
  const mentioned = data.mentioned_companies || '';
  const file = data.file_name || '';
  const uid = data.uid || '';

  // Core content fields
  const coreSummary = data.core_summary || '';
  const keyPoints = data.key_points || '';
  const fullContent = data.full_content || '';
  const qna = data.q_n_a || '';
  const transcript = data.transcript_content || '';

  // Determine if sentiment is bullish/bearish
  let sentimentClass = 'sentiment-neutral';
  let sentimentIcon = '◈';
  if (sentimentVal != null) {
    if (sentimentVal > 0) { sentimentClass = 'sentiment-bullish'; sentimentIcon = '▲'; }
    else if (sentimentVal < 0) { sentimentClass = 'sentiment-bearish'; sentimentIcon = '▼'; }
  } else {
    const s = (sentiment || '').toLowerCase();
    if (s.includes('bullish') || s.includes('+')) { sentimentClass = 'sentiment-bullish'; sentimentIcon = '▲'; }
    else if (s.includes('bearish') || s.includes('-')) { sentimentClass = 'sentiment-bearish'; sentimentIcon = '▼'; }
  }

  // Build a tabbed content area
  const _has = (v) => v && v.trim().length > 3;
  const tabs = [];
  if (_has(coreSummary) || _has(keyPoints)) tabs.push('summary');
  if (_has(fullContent)) tabs.push('full_content');
  if (_has(qna)) tabs.push('qna');
  if (_has(transcript)) tabs.push('transcript');
  if (!tabs.length) tabs.push('summary');

  let firstTab = true;
  let tabButtons = '';
  let tabContents = '';
  for (const t of tabs) {
    const active = firstTab ? ' active' : '';
    firstTab = false;
    const label = { summary: 'Summary', full_content: 'Full Content', qna: 'Q&A', transcript: 'Transcript' }[t] || t;
    tabButtons += `<button class="md-tab${active}" data-md-panel="${t}">${label}</button>`;

    let bodyHtml = '';
    if (t === 'summary') {
      const parts = [];
      if (_has(coreSummary)) parts.push(`<div class="md-section"><h4 class="md-section-title">Core Summary</h4><div class="md-body-text">${markdownModule.processWithThinking(esc(coreSummary))}</div></div>`);
      if (_has(keyPoints)) parts.push(`<div class="md-section"><h4 class="md-section-title">Key Points</h4><div class="md-body-text">${markdownModule.processWithThinking(esc(keyPoints))}</div></div>`);
      bodyHtml = parts.join('\n') || '<div class="md-empty">No summary available.</div>';
    } else if (t === 'full_content') {
      bodyHtml = `<div class="md-section"><div class="md-body-text">${markdownModule.processWithThinking(esc(fullContent))}</div></div>`;
    } else if (t === 'qna') {
      bodyHtml = `<div class="md-section"><div class="md-body-text">${markdownModule.processWithThinking(esc(qna))}</div></div>`;
    } else if (t === 'transcript') {
      bodyHtml = `<div class="md-section"><div class="md-body-text"><pre style="white-space:pre-wrap;font-family:var(--font-mono, monospace);font-size:0.85em;line-height:1.4;">${esc(transcript)}</pre></div></div>`;
    }
    tabContents += `<div class="md-panel${active}" data-md-panel="${t}">${bodyHtml}</div>`;
  }

  const modalHtml = `
    <div id="meeting-detail-modal" class="modal md-modal">
      <div class="modal-content md-modal-content" role="dialog" aria-label="Meeting Detail">
        <div class="modal-header md-header">
          <div class="md-header-info">
            <span class="md-company">${esc(company)}</span>
            <span class="md-date">${esc(meetingDate)}</span>
            ${sourceTag ? `<span class="md-tag">${esc(sourceTag)}</span>` : ''}
            <span class="md-sentiment ${sentimentClass}">${sentimentIcon}</span>
          </div>
          <div class="md-header-actions">
            ${uid ? `<a href="/meetings?uid=${esc(uid)}" target="_blank" class="md-open-btn" title="Open in meetings page">↗</a>` : ''}
            <button class="close-btn md-close-btn" id="md-close-btn" aria-label="Close">✖</button>
          </div>
        </div>

        <div class="md-meta-bar">
          ${industry ? `<span class="md-meta-item"><span class="md-meta-label">Industry</span> ${esc(industry)}</span>` : ''}
          ${keywords ? `<span class="md-meta-item"><span class="md-meta-label">Keywords</span> ${esc(keywords)}</span>` : ''}
          ${file ? `<span class="md-meta-item"><span class="md-meta-label">File</span> ${esc(file)}</span>` : ''}
          ${sentiment ? `<span class="md-meta-item"><span class="md-meta-label">Sentiment</span> <span class="${sentimentClass}">${esc(sentiment)}</span></span>` : ''}
        </div>

        ${mentioned ? `<div class="md-companies-bar"><span class="md-meta-label">Mentioned:</span> ${mentioned.split(',').map(c => `<span class="md-company-chip">${esc(c.trim())}</span>`).join(' ')}</div>` : ''}

        <div class="md-tab-bar">${tabButtons}</div>
        <div class="md-body">${tabContents}</div>
      </div>
    </div>`;

  // Inject into body
  const wrapper = document.createElement('div');
  wrapper.innerHTML = modalHtml;
  _modalEl = wrapper.firstElementChild;
  document.body.appendChild(_modalEl);

  // Show with animation
  requestAnimationFrame(() => { _modalEl.classList.remove('hidden'); });

  // Wire tab switching
  _modalEl.querySelectorAll('.md-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const panel = btn.dataset.mdPanel;
      _modalEl.querySelectorAll('.md-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _modalEl.querySelectorAll('.md-panel').forEach(p => p.classList.remove('active'));
      const target = _modalEl.querySelector(`.md-panel[data-md-panel="${panel}"]`);
      if (target) target.classList.add('active');
    });
  });

  // Wire close
  const closeBtn = _modalEl.querySelector('#md-close-btn');
  if (closeBtn) closeBtn.addEventListener('click', closeMeetingModal);

  // Click outside modal-content to close
  _modalEl.addEventListener('click', (e) => {
    if (e.target === _modalEl) closeMeetingModal();
  });

  // Highlight code blocks
  if (window.hljs) {
    _modalEl.querySelectorAll('pre code:not(.hljs)').forEach(b => window.hljs.highlightElement(b));
  }

  // ESC to close
  _closeHandler = bindMenuDismiss(_modalEl, closeMeetingModal);
}

// ── Show from source_id (primary entry point) ───────────────────────────────

export async function showMeetingFromSource(sourceId) {
  if (!sourceId) return;
  // Show loading overlay
  const spinner = uiModule.showLoading ? uiModule.showLoading('Loading meeting...') : null;
  try {
    const data = await fetchMeetingBySource(sourceId);
    if (!data || !data.uid) {
      if (uiModule.showToast) uiModule.showToast('Meeting not found', 3000, 'error');
      return;
    }
    renderMeetingModal(data);
  } catch (err) {
    console.error('[meetingDetail] fetch failed:', err);
    if (uiModule.showToast) uiModule.showToast('Failed to load meeting: ' + err.message, 4000, 'error');
  } finally {
    if (spinner && typeof spinner.remove === 'function') spinner.remove();
  }
}

// ── Close ────────────────────────────────────────────────────────────────────

export function closeMeetingModal() {
  if (_closeHandler && typeof _closeHandler === 'function') {
    try { _closeHandler(); } catch (_) {}
    _closeHandler = null;
  }
  if (_modalEl) {
    _modalEl.remove();
    _modalEl = null;
  }
  // Re-focus the chat input
  const msgInput = document.getElementById('message');
  if (msgInput) setTimeout(() => msgInput.focus(), 50);
}

// ── Post-process chat messages: auto-link source_id patterns ────────────────

export function linkSourceCitations(containerEl) {
  if (!containerEl) return;
  // Walk all text nodes in .msg-ai .body looking for source_XXXXX patterns
  const walker = document.createTreeWalker(
    containerEl,
    NodeFilter.SHOW_TEXT,
    null,
    false
  );
  const replacements = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = node.textContent || '';
    // Match patterns like: source_XXXXX or (source_XXXXX)
    const regex = /(?:^|[\s(])source_([a-zA-Z0-9]{8,})(?=[\s).,;:!?]|$)/g;
    let match;
    while ((match = regex.exec(text)) !== null) {
      const fullMatch = match[0];
      const sourceId = 'source_' + match[1];
      const idx = match.index;
      const prefix = text[idx] === '(' ? '(' : '';
      const after = text.substring(idx + fullMatch.length, idx + fullMatch.length + 1) === ')' ? ')' : '';
      replacements.push({
        node,
        start: idx,
        end: idx + fullMatch.length,
        sourceId,
        display: fullMatch.trim(),
      });
    }
  }

  // Apply replacements in reverse order (to preserve offsets)
  for (const r of replacements.reverse()) {
    const range = document.createRange();
    range.setStart(r.node, r.start);
    range.setEnd(r.node, r.end);

    const link = document.createElement('a');
    link.href = '#';
    link.className = 'md-source-link';
    link.dataset.sourceId = r.sourceId;
    link.textContent = r.display;
    link.title = `View meeting: ${r.sourceId}`;
    link.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      showMeetingFromSource(r.sourceId);
    });

    range.deleteContents();
    range.insertNode(link);
  }
}

// ── Init: global click delegation ────────────────────────────────────────────

export function initMeetingDetail() {
  // Global click handler for any /meetings?uid=xxx links inside chat messages
  document.addEventListener('click', (e) => {
    const link = e.target.closest('a[href^="/meetings?"]');
    if (!link) return;
    // Only intercept clicks inside chat area
    if (!link.closest('#chat-history, .msg, .md-modal')) return;
    e.preventDefault();
    const url = new URL(link.href, window.location.origin);
    const uid = url.searchParams.get('uid');
    if (uid) {
      // Fetch by uid directly from odysseus API
      showMeetingByUid(uid);
    }
  });
}

async function showMeetingByUid(uid) {
  const spinner = uiModule.showLoading ? uiModule.showLoading('Loading meeting...') : null;
  try {
    // Use the existing kb source resolution: search for matching meetings
    const res = await fetch(`/api/v1/meetings/${encodeURIComponent(uid)}`, {
      credentials: 'same-origin',
    });
    if (!res.ok) throw new Error(`Meeting lookup failed: ${res.status}`);
    const data = await res.json();
    renderMeetingModal(data);
  } catch (err) {
    console.error('[meetingDetail] uid fetch failed:', err);
    // Fallback: try the kb source endpoint with source_ prefix
    try {
      const data = await fetchMeetingBySource('source_' + uid.slice(0, 8));
      if (data && data.uid) { renderMeetingModal(data); return; }
    } catch (_) {}
    if (uiModule.showToast) uiModule.showToast('Failed to load meeting', 4000, 'error');
  } finally {
    if (spinner && typeof spinner.remove === 'function') spinner.remove();
  }
}
