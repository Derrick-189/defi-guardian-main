/**
 * dashboard.js — Dashboard real-time data for DeFi Guardian
 */
(function () {
  'use strict';

  // ── Helpers ──────────────────────────────────────────────────────────────

  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = (val !== undefined && val !== null && val !== '') ? val : '—';
  }

  function fmtTime(ts) {
    if (!ts) return 'Never';
    try { return new Date(ts).toLocaleTimeString(); } catch(e) { return String(ts).slice(0,16); }
  }

  function fmtNum(n) {
    if (n === undefined || n === null || n === '' || n === 0) return '—';
    return Number(n).toLocaleString();
  }

  // ── KPI population ───────────────────────────────────────────────────────
  // verification_state.json keys: states_stored, transitions, depth, ltl_results (array)

  function populateKPIs(data) {
    if (!data || typeof data !== 'object') return;

    // States — key is states_stored in verification_state.json
    var states = data.states_stored || data.states_explored || data.states || null;
    setText('kpi-states', states ? fmtNum(states) : '—');

    // Transitions
    var trans = data.transitions || null;
    setText('kpi-transitions', trans ? fmtNum(trans) : '—');

    // Depth — key is depth in verification_state.json
    var depth = data.depth || data.max_depth || data.depth_reached || null;
    setText('kpi-depth', depth ? fmtNum(depth) : '—');

    // LTL pass/fail — ltl_results is an array of {name, success, formula, errors}
    var ltl = data.ltl_results || [];
    if (!Array.isArray(ltl)) ltl = Object.values(ltl);
    var pass = 0, fail = 0;
    ltl.forEach(function (r) {
      if (r.success === true || r.status === 'PASS' || r.status === 'VERIFIED') pass++;
      else fail++;
    });
    setText('kpi-ltl-pass', ltl.length ? pass : '—');
    setText('kpi-ltl-fail', ltl.length ? fail : '—');

    // Render SPIN stats panel
    renderSpinStats(data);
  }

  function renderSpinStats(data) {
    var el = document.getElementById('spin-stats');
    if (!el) return;
    var spin = data.spin || data;
    var items = [
      ['States stored',  spin.states_stored  || spin.states || '—'],
      ['Transitions',    spin.transitions    || '—'],
      ['Depth reached',  spin.depth          || spin.depth_reached || '—'],
      ['Model',          spin.model_name     || data.model_name || '—'],
      ['Last run',       spin.timestamp ? new Date(spin.timestamp).toLocaleString() : (data.datetime || '—')],
    ];
    el.innerHTML = items.map(function (item) {
      return '<div class="tool-status-item">' +
        '<span class="tool-status-name text-muted" style="font-weight:400;">' + esc(item[0]) + '</span>' +
        '<span class="font-mono" style="font-size:0.8rem;">' + esc(String(item[1])) + '</span>' +
      '</div>';
    }).join('');
  }

  // ── Tool status list (single-column, no overflow) ─────────────────────────

  var TOOL_COLORS = {
    SPIN:'#58a6ff', COQ:'#bc8cff', LEAN:'#3fb950', CERTORA:'#f78166',
    KANI:'#d29922', PRUSTI:'#79c0ff', CREUSOT:'#56d364', VERUS:'#ff7b72'
  };

  function renderToolStatusList(toolsData) {
    var el = document.getElementById('tools-status-list');
    if (!el) return;
    if (!toolsData || !Object.keys(toolsData).length) {
      el.innerHTML = '<p class="text-muted text-sm">No tool data.</p>';
      return;
    }

    // Update KPI tools count
    var availCount = Object.values(toolsData).filter(function (t) { return t.available; }).length;
    setText('kpi-tools', availCount + ' / ' + Object.keys(toolsData).length);

    el.innerHTML = Object.entries(toolsData).map(function (entry) {
      var name = entry[0];
      var d    = entry[1] || {};
      var status = (d.last_status || d.status || 'UNKNOWN').toUpperCase();
      var avail  = d.available;
      var color  = TOOL_COLORS[name] || '#8b949e';

      var badgeCls = 'badge-tool';
      if (status === 'PASS' || status === 'VERIFIED')   badgeCls = 'badge-pass';
      else if (status === 'FAIL' || status === 'VIOLATED') badgeCls = 'badge-fail';
      else if (status === 'TIMEOUT')                    badgeCls = 'badge-timeout';
      else if (status === 'RUNNING')                    badgeCls = 'badge-running';

      return '<div class="tool-status-item" data-tool="' + esc(name) + '">' +
        '<div style="display:flex;align-items:center;gap:0.5rem;">' +
          '<span style="width:8px;height:8px;border-radius:50%;background:' + color + ';flex-shrink:0;display:inline-block;"></span>' +
          '<span class="tool-status-name">' + esc(name) + '</span>' +
        '</div>' +
        '<div class="tool-status-meta">' +
          '<span class="badge ' + badgeCls + '" style="font-size:0.65rem;">' + esc(status) + '</span>' +
          '<span class="tool-avail-dot ' + (avail ? 'avail' : 'sim') + '">' +
            (avail ? '● Available' : '○ Simulated') +
          '</span>' +
          (d.last_run ? '<span class="tool-last-run-time">' + esc(fmtTime(d.last_run)) + '</span>' : '') +
        '</div>' +
      '</div>';
    }).join('');
  }

  // ── LTL table ─────────────────────────────────────────────────────────────

  function renderLTLTable(ltl) {
    var tbody = document.getElementById('ltl-table');
    if (!tbody) return;
    if (!ltl || !ltl.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-muted text-sm" style="text-align:center;padding:1.5rem;">No LTL data — run SPIN verification first.</td></tr>';
      return;
    }
    tbody.innerHTML = ltl.map(function (r) {
      var name    = r.name    || '?';
      var formula = r.formula || '';
      var passed  = r.success === true || r.status === 'PASS' || r.status === 'VERIFIED';
      var errors  = r.errors  || 0;
      var badgeCls = passed ? 'badge-pass' : 'badge-fail';
      var statusTxt = passed ? 'VERIFIED' : 'VIOLATED';
      return '<tr>' +
        '<td class="font-mono" style="font-size:0.8rem;">' + esc(name) + '</td>' +
        '<td class="font-mono text-muted" style="font-size:0.75rem;word-break:break-all;">' + esc(formula) + '</td>' +
        '<td><span class="badge ' + badgeCls + '">' + statusTxt + '</span></td>' +
        '<td class="font-mono text-sm">' + (errors > 0 ? '<span class="text-danger">' + errors + '</span>' : '0') + '</td>' +
      '</tr>';
    }).join('');
  }

  // ── Live feed ─────────────────────────────────────────────────────────────

  function addFeedRow(data) {
    var feed = document.getElementById('live-feed');
    if (!feed) return;

    // Remove placeholder
    var placeholder = feed.querySelector('p');
    if (placeholder) placeholder.remove();

    var tool   = esc(data.tool     || 'Unknown');
    var status = (data.status || 'UNKNOWN').toUpperCase();
    var file   = esc(data.filename || '');
    var time   = fmtTime(data.timestamp || Date.now());

    var badgeCls = 'badge-tool';
    if (status === 'PASS' || status === 'VERIFIED')   badgeCls = 'badge-pass';
    else if (status === 'FAIL' || status === 'VIOLATED') badgeCls = 'badge-fail';
    else if (status === 'TIMEOUT')                    badgeCls = 'badge-timeout';

    var row = document.createElement('div');
    row.className = 'feed-item';
    row.innerHTML =
      '<span class="feed-time">' + esc(time) + '</span>' +
      '<span class="feed-tool">' + tool + '</span>' +
      '<span class="badge ' + badgeCls + '" style="font-size:0.65rem;">' + esc(status) + '</span>' +
      (file ? '<span class="feed-file">' + file + '</span>' : '');

    feed.insertBefore(row, feed.firstChild);

    // Cap at 30 items
    var items = feed.querySelectorAll('.feed-item');
    if (items.length > 30) feed.removeChild(items[items.length - 1]);
  }

  // ── Data fetching ─────────────────────────────────────────────────────────

  function fetchState() {
    fetch('/api/v1/state/current', { credentials:'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) { populateKPIs(d); renderLTLTable(d.ltl_results || []); } })
      .catch(function () {});
  }

  function fetchTools() {
    fetch('/api/v1/tools/status', { credentials:'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) renderToolStatusList(d); })
      .catch(function () {});
  }

  function fetchLTL() {
    fetch('/api/v1/ltl-properties', { credentials:'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && Array.isArray(d) && d.length) renderLTLTable(d); })
      .catch(function () {});
  }

  function refreshAll() { fetchState(); fetchTools(); fetchLTL(); }

  // ── Real-time events ──────────────────────────────────────────────────────

  document.addEventListener('dg:state_update', function (e) {
    if (e.detail) { populateKPIs(e.detail); renderLTLTable(e.detail.ltl_results || []); }
  });

  document.addEventListener('dg:verification_complete', function (e) {
    if (e.detail) addFeedRow(e.detail);
    fetchTools();
    fetchLTL();
  });

  // ── Init ──────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    refreshAll();
    setInterval(refreshAll, 10000);
  });

})();
