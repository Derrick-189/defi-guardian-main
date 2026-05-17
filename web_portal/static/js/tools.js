/**
 * tools.js — Tools page logic for DeepGuard portal
 */
(function () {
  'use strict';

  // ── Tool metadata ────────────────────────────────────────────────────────

  const TOOL_DESCRIPTIONS = {
    SPIN:    'State-space exhaustive search, LTL properties',
    COQ:     'Formal theorem proving',
    LEAN:    'Lean 4 type-theoretic proofs',
    CERTORA: 'Cloud bytecode verification',
    KANI:    'Bounded model checking',
    PRUSTI:  'Deductive verification',
    CREUSOT: 'Why3 backend proofs',
    VERUS:   'SMT-based verification',
  };

  const TOOL_COLORS = {
    SPIN:    '#58a6ff',
    COQ:     '#bc8cff',
    LEAN:    '#3fb950',
    CERTORA: '#f78166',
    KANI:    '#d29922',
    PRUSTI:  '#79c0ff',
    CREUSOT: '#56d364',
    VERUS:   '#ff7b72',
  };

  const TOOL_LANGS = {
    SPIN:    'Promela',
    COQ:     'Gallina / Coq',
    LEAN:    'Lean 4',
    CERTORA: 'CVL / Solidity',
    KANI:    'Rust',
    PRUSTI:  'Rust',
    CREUSOT: 'Rust',
    VERUS:   'Rust',
  };

  // ── Helpers ──────────────────────────────────────────────────────────────

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatTime(ts) {
    if (!ts) return 'Never';
    try {
      return new Date(ts).toLocaleString();
    } catch (e) {
      return String(ts);
    }
  }

  function getCurrentFilename() {
    // Try to read from a global set by the page, or a data attribute
    if (window.DG_CURRENT_FILE) return window.DG_CURRENT_FILE;
    const el = document.querySelector('[data-current-file]');
    return el ? el.getAttribute('data-current-file') : '';
  }

  // ── Card rendering ───────────────────────────────────────────────────────

  /**
   * Build the HTML for a single tool card.
   * @param {string} toolName
   * @param {Object} data  - API data for this tool
   * @returns {string}
   */
  function buildToolCard(toolName, data) {
    const color = TOOL_COLORS[toolName] || '#8b949e';
    const desc = TOOL_DESCRIPTIONS[toolName] || '';
    const lang = TOOL_LANGS[toolName] || '';
    const available = data && data.available;
    const status = (data && data.status) ? data.status : 'UNKNOWN';
    const lastRun = (data && data.last_run) ? formatTime(data.last_run) : 'Never';
    const version = (data && data.version) ? data.version : '';

    const sl = status.toLowerCase();
    let badgeClass = 'badge-tool';
    if (sl === 'pass' || sl === 'verified') badgeClass = 'badge-pass';
    else if (sl === 'fail' || sl === 'violated') badgeClass = 'badge-fail';
    else if (sl === 'timeout') badgeClass = 'badge-timeout';
    else if (sl === 'running') badgeClass = 'badge-running';

    const availHtml = available
      ? '<span class="tool-available">● Available</span>'
      : '<span class="tool-unavailable">○ Simulated</span>';

    const initial = toolName.charAt(0);

    return (
      '<div class="tool-card" id="tool-card-' + escapeHtml(toolName) + '" data-tool="' + escapeHtml(toolName) + '">' +
        '<div class="tool-card-header">' +
          '<div class="tool-icon" style="background:' + color + '22;color:' + color + ';">' +
            escapeHtml(initial) +
          '</div>' +
          '<div>' +
            '<div class="tool-name">' + escapeHtml(toolName) + '</div>' +
            '<div class="tool-lang">' + escapeHtml(lang) + (version ? ' · ' + escapeHtml(version) : '') + '</div>' +
          '</div>' +
        '</div>' +

        (desc
          ? '<div class="text-muted" style="font-size:0.8rem;">' + escapeHtml(desc) + '</div>'
          : '') +

        '<div class="tool-status-row">' +
          '<span class="badge ' + badgeClass + ' tool-status-badge">' + escapeHtml(status) + '</span>' +
          availHtml +
        '</div>' +

        '<div class="text-muted" style="font-size:0.75rem;">Last run: <span class="tool-last-run">' + escapeHtml(lastRun) + '</span></div>' +

        '<button class="btn btn-secondary btn-sm tool-run-btn" data-tool="' + escapeHtml(toolName) + '">' +
          '<span class="run-label">▶ Run</span>' +
          '<span class="run-spinner hidden"><span class="spinner" style="width:14px;height:14px;border-width:2px;"></span></span>' +
        '</button>' +
      '</div>'
    );
  }

  // ── Grid rendering ───────────────────────────────────────────────────────

  function renderToolsGrid(toolsData) {
    const grid = document.getElementById('tools-grid');
    if (!grid) return;

    if (!toolsData || Object.keys(toolsData).length === 0) {
      grid.innerHTML =
        '<div class="empty-state">' +
          '<span class="empty-state-icon">🔧</span>' +
          '<div class="empty-state-title">No tools found</div>' +
          '<div class="empty-state-desc">Configure verification tools to get started.</div>' +
        '</div>';
      return;
    }

    grid.innerHTML = Object.entries(toolsData)
      .map(function (entry) { return buildToolCard(entry[0], entry[1]); })
      .join('');

    // Wire up run buttons
    grid.querySelectorAll('.tool-run-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const tool = btn.getAttribute('data-tool');
        runTool(tool, btn);
      });
    });
  }

  // ── Update a single card in-place ────────────────────────────────────────

  function updateToolCard(toolName, data) {
    const card = document.getElementById('tool-card-' + toolName);
    if (!card) return;

    const status = (data && data.status) ? data.status : 'UNKNOWN';
    const lastRun = (data && data.last_run) ? formatTime(data.last_run) : 'Never';

    const sl = status.toLowerCase();
    let badgeClass = 'badge-tool';
    if (sl === 'pass' || sl === 'verified') badgeClass = 'badge-pass';
    else if (sl === 'fail' || sl === 'violated') badgeClass = 'badge-fail';
    else if (sl === 'timeout') badgeClass = 'badge-timeout';
    else if (sl === 'running') badgeClass = 'badge-running';

    const badge = card.querySelector('.tool-status-badge');
    if (badge) {
      badge.className = 'badge ' + badgeClass + ' tool-status-badge';
      badge.textContent = status;
    }

    const lastRunEl = card.querySelector('.tool-last-run');
    if (lastRunEl) lastRunEl.textContent = lastRun;
  }

  // ── Run tool ─────────────────────────────────────────────────────────────

  function runTool(toolName, btn) {
    const filename = getCurrentFilename();
    const label = btn.querySelector('.run-label');
    const spinner = btn.querySelector('.run-spinner');

    // Show spinner
    btn.disabled = true;
    if (label) label.classList.add('hidden');
    if (spinner) spinner.classList.remove('hidden');

    // Optimistically mark as running
    updateToolCard(toolName, { status: 'RUNNING' });

    fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ tool: toolName, filename: filename }),
    })
      .then(function (r) {
        if (!r.ok) return Promise.reject('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        updateToolCard(toolName, data);
        if (window.DGSocket && window.DGSocket.showToast) {
          const status = (data.status || 'UNKNOWN').toUpperCase();
          const type = ['PASS', 'VERIFIED'].includes(status) ? 'success'
            : ['FAIL', 'VIOLATED'].includes(status) ? 'danger'
            : status === 'TIMEOUT' ? 'warning' : 'info';
          window.DGSocket.showToast(toolName, status, type);
        }
      })
      .catch(function (err) {
        console.error('[Tools] Run failed for', toolName, ':', err);
        updateToolCard(toolName, { status: 'ERROR' });
        if (window.DGSocket && window.DGSocket.showToast) {
          window.DGSocket.showToast(toolName, 'Run failed: ' + String(err), 'danger');
        }
      })
      .finally(function () {
        btn.disabled = false;
        if (label) label.classList.remove('hidden');
        if (spinner) spinner.classList.add('hidden');
      });
  }

  // ── Real-time updates ────────────────────────────────────────────────────

  document.addEventListener('dg:verification_complete', function (e) {
    const data = e.detail;
    if (!data || !data.tool) return;
    updateToolCard(data.tool, data);
  });

  // ── Data loading ─────────────────────────────────────────────────────────

  function loadTools() {
    const grid = document.getElementById('tools-grid');
    if (grid) {
      grid.innerHTML =
        '<div style="display:flex;justify-content:center;padding:3rem;">' +
          '<span class="spinner"></span>' +
        '</div>';
    }

    fetch('/api/tools/status', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) return Promise.reject('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        renderToolsGrid(data);
      })
      .catch(function (err) {
        console.error('[Tools] Failed to load tools:', err);
        if (grid) {
          grid.innerHTML =
            '<div class="empty-state">' +
              '<span class="empty-state-icon">⚠️</span>' +
              '<div class="empty-state-title">Failed to load tools</div>' +
              '<div class="empty-state-desc">' + escapeHtml(String(err)) + '</div>' +
            '</div>';
        }
      });
  }

  // ── Init ─────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    loadTools();
  });
})();
