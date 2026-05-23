/**
 * dashboard_fixed.js — Dashboard real-time data for DeFi Guardian
 *
 * Fixes:
 *  • KPIs now populate from /api/v1/dashboard/summary (DB) when
 *    verification_state.json is absent or stale (web-portal runs).
 *  • Tools status list always renders — merges DB last-known status.
 *  • Recent runs list is fetched from /api/v1/runs/recent (unified
 *    desktop + web-portal source), shown in the runs table via JS.
 *
 * Replace:  web_portal/static/js/dashboard.js  with this file.
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

  function populateKPIs(data) {
    if (!data || typeof data !== 'object') return;

    // From /api/v1/state/current (verification_state.json + DB enrichment)
    var states = data.states_stored || data.latest_states || data.states_explored || data.states || null;
    setText('kpi-states', states ? fmtNum(states) : '—');

    var trans = data.transitions || data.latest_trans || null;
    setText('kpi-transitions', trans ? fmtNum(trans) : '—');

    var depth = data.depth || data.latest_depth || data.max_depth || data.depth_reached || null;
    setText('kpi-depth', depth ? fmtNum(depth) : '—');

    // Tools available from summary or state
    if (data.tools_available !== undefined) {
      setText('kpi-tools', data.tools_available + ' / 8');
    }

    // LTL pass / fail — from state or summary
    var ltlPass = data.ltl_pass;
    var ltlFail = data.ltl_fail;

    // Also parse ltl_results array if present
    var ltl = data.ltl_results || [];
    if (!Array.isArray(ltl)) ltl = Object.values(ltl);
    if (ltl.length && ltlPass === undefined) {
      ltlPass = 0; ltlFail = 0;
      ltl.forEach(function (r) {
        if (r.success === true || r.status === 'PASS' || r.status === 'VERIFIED') ltlPass++;
        else ltlFail++;
      });
    }

    if (ltlPass !== undefined) setText('kpi-ltl-pass', ltlPass);
    if (ltlFail !== undefined) setText('kpi-ltl-fail', ltlFail);

    renderSpinStats(data);
  }

  // Also accepts the /api/v1/dashboard/summary shape
  function populateKPIsFromSummary(d) {
    if (!d) return;
    setText('kpi-states',      d.latest_states  ? fmtNum(d.latest_states)  : '—');
    setText('kpi-transitions', d.latest_trans   ? fmtNum(d.latest_trans)   : '—');
    setText('kpi-depth',       d.latest_depth   ? fmtNum(d.latest_depth)   : '—');
    setText('kpi-ltl-pass',    d.ltl_pass !== undefined ? d.ltl_pass : '—');
    setText('kpi-ltl-fail',    d.ltl_fail !== undefined ? d.ltl_fail : '—');
    setText('kpi-tools',       d.tools_available !== undefined ? d.tools_available + ' / 8' : '—');

    // Spin stats panel
    renderSpinStats({
      states_stored: d.latest_states,
      transitions:   d.latest_trans,
      depth:         d.latest_depth,
      model_name:    d.latest_file,
      datetime:      d.latest_date,
    });
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

  // ── Tool status list ─────────────────────────────────────────────────────

  var TOOL_COLORS = {
    SPIN:'#58a6ff', COQ:'#bc8cff', LEAN:'#3fb950', CERTORA:'#f78166',
    KANI:'#d29922', PRUSTI:'#79c0ff', CREUSOT:'#56d364', VERUS:'#ff7b72'
  };

  function renderToolStatusList(toolsData) {
    var el = document.getElementById('tools-status-list');
    if (!el) return;

    // If toolsData is null/empty — show skeleton instead of spinner forever
    if (!toolsData || !Object.keys(toolsData).length) {
      el.innerHTML = '<p class="text-muted text-sm" style="padding:0.75rem;">No tool status available — run a verification first.</p>';
      return;
    }

    // Update KPI tools count
    var availCount = Object.values(toolsData).filter(function (t) { return t.available; }).length;
    // Only update if not already set by summary
    var kpiEl = document.getElementById('kpi-tools');
    if (kpiEl && (kpiEl.textContent === '—' || !kpiEl.textContent)) {
      setText('kpi-tools', availCount + ' / ' + Object.keys(toolsData).length);
    }

    el.innerHTML = Object.entries(toolsData).map(function (entry) {
      var name = entry[0];
      var d    = entry[1] || {};
      var status = (d.last_status || d.status || 'UNKNOWN').toUpperCase();
      var avail  = d.available;
      var color  = TOOL_COLORS[name] || '#8b949e';

      var badgeCls = 'badge-tool';
      if (status === 'PASS' || status === 'VERIFIED')      badgeCls = 'badge-pass';
      else if (status === 'FAIL' || status === 'VIOLATED') badgeCls = 'badge-fail';
      else if (status === 'TIMEOUT')                       badgeCls = 'badge-timeout';
      else if (status === 'RUNNING')                       badgeCls = 'badge-running';

      var sourceBadge = d.source === 'web_portal'
        ? '<span style="font-size:0.6rem;color:var(--accent);margin-left:2px;" title="Last run from web portal">●WEB</span>'
        : (d.has_db_data ? '<span style="font-size:0.6rem;color:var(--text2);" title="Last run from desktop">●DSK</span>' : '');

      return '<div class="tool-status-item" data-tool="' + esc(name) + '">' +
        '<div style="display:flex;align-items:center;gap:0.5rem;">' +
          '<span style="width:8px;height:8px;border-radius:50%;background:' + color + ';flex-shrink:0;display:inline-block;"></span>' +
          '<span class="tool-status-name">' + esc(name) + '</span>' +
          sourceBadge +
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
      var badgeCls = passed ? 'badge-pass' : (r.status === 'UNKNOWN' ? 'badge-tool' : 'badge-fail');
      var statusTxt = r.status === 'UNKNOWN' ? 'UNKNOWN' : (passed ? 'VERIFIED' : 'VIOLATED');
      return '<tr>' +
        '<td class="font-mono" style="font-size:0.8rem;">' + esc(name) + '</td>' +
        '<td class="font-mono text-muted" style="font-size:0.75rem;word-break:break-all;">' + esc(formula) + '</td>' +
        '<td><span class="badge ' + badgeCls + '">' + statusTxt + '</span></td>' +
        '<td class="font-mono text-sm">' + (errors > 0 ? '<span class="text-danger">' + errors + '</span>' : (errors === -1 ? '?' : '0')) + '</td>' +
      '</tr>';
    }).join('');
  }

  // ── Live feed ─────────────────────────────────────────────────────────────

  function addFeedRow(data) {
    var feed = document.getElementById('live-feed');
    if (!feed) return;

    var placeholder = feed.querySelector('p');
    if (placeholder) placeholder.remove();

    var tool   = esc(data.tool     || 'Unknown');
    var status = (data.status || 'UNKNOWN').toUpperCase();
    var file   = esc(data.filename || data.file || '');
    var time   = fmtTime(data.timestamp || Date.now());
    var source = data.source === 'web_portal'
      ? '<span style="font-size:0.6rem;color:var(--accent);margin-left:4px;">[WEB]</span>'
      : '';

    var badgeCls = 'badge-tool';
    if (status === 'PASS' || status === 'VERIFIED')      badgeCls = 'badge-pass';
    else if (status === 'FAIL' || status === 'VIOLATED') badgeCls = 'badge-fail';
    else if (status === 'TIMEOUT')                       badgeCls = 'badge-timeout';

    var row = document.createElement('div');
    row.className = 'feed-item';
    row.innerHTML =
      '<span class="feed-time">' + esc(time) + '</span>' +
      '<span class="feed-tool">' + tool + source + '</span>' +
      '<span class="badge ' + badgeCls + '" style="font-size:0.65rem;">' + esc(status) + '</span>' +
      (file ? '<span class="feed-file">' + file + '</span>' : '');

    feed.insertBefore(row, feed.firstChild);

    var items = feed.querySelectorAll('.feed-item');
    if (items.length > 30) feed.removeChild(items[items.length - 1]);
  }

  // ── Populate run table from JS (so web-portal runs appear immediately) ────

  function populateRunsTable(runs) {
    // If the server already rendered rows via Jinja, don't overwrite unless
    // we actually have more/newer data.
    var tbody = document.getElementById('runs-tbody');
    if (!tbody) return;
    if (!runs || !runs.length) return;

    // Check if table already has real rows
    var existingRows = tbody.querySelectorAll('tr.run-row');
    // Only inject if table is empty or we have more rows
    if (existingRows.length >= runs.length) return;

    tbody.innerHTML = runs.map(function (r) {
      var s = (r.status || '').toUpperCase();
      var badgeCls = s === 'PASS' ? 'badge-pass' : s === 'FAIL' ? 'badge-fail' : 'badge-tool';
      var toolColor = TOOL_COLORS[r.tool] || '#8b949e';
      var srcBadge = r.source === 'web_portal'
        ? '<span style="font-size:0.6rem;color:var(--accent);" title="Web portal run">WEB</span>'
        : '<span style="font-size:0.6rem;color:var(--text2);" title="Desktop run">DSK</span>';

      return '<tr class="run-row" data-tool="' + esc(r.tool) + '" data-status="' + esc(s) + '" data-file="' + esc((r.file||'').toLowerCase()) + '">' +
        '<td class="font-mono text-sm">' + esc((r.file || '—').slice(0, 28)) + '</td>' +
        '<td>' +
          '<span class="badge badge-tool" style="background:' + toolColor + '20;color:' + toolColor + ';border-color:' + toolColor + '40;">' + esc(r.tool || '—') + '</span>' +
          '&nbsp;' + srcBadge +
        '</td>' +
        '<td><span class="badge ' + badgeCls + '">' + esc(s || '?') + '</span></td>' +
        '<td class="font-mono">' + (r.states || '—') + '</td>' +
        '<td class="font-mono">' + (r.depth || '—') + '</td>' +
        '<td class="text-muted text-sm">' + esc(r.date_short || '') + '</td>' +
        '<td>' +
          '<div class="action-group">' +
            '<a href="' + esc(r.audit_url) + '" class="btn btn-xs btn-secondary" title="Counterexample Analysis"><i class="fa-solid fa-magnifying-glass"></i></a>' +
            (r.has_trace ? '<a href="' + esc(r.trace_url) + '" class="btn btn-xs btn-secondary" title="Trace Viewer"><i class="fa-solid fa-chart-line"></i></a>' : '') +
          '</div>' +
        '</td>' +
      '</tr>';
    }).join('');

    // Re-attach filter listeners to new rows
    rows = Array.from(document.querySelectorAll('.run-row'));
    applyFilters();
  }

  // ── Data fetching ─────────────────────────────────────────────────────────

  function fetchState() {
    fetch('/api/v1/state/current', { credentials:'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d) {
          // Only use state data if it has meaningful values
          var hasData = d.states_stored || d.transitions || d.depth || (d.ltl_results && d.ltl_results.length);
          if (hasData) {
            populateKPIs(d);
            renderLTLTable(d.ltl_results || []);
          }
        }
      })
      .catch(function () {});
  }

  function fetchSummary() {
    fetch('/api/v1/dashboard/summary', { credentials:'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && !d.error) {
          populateKPIsFromSummary(d);
          // Update run source counter if element exists
          var srcEl = document.getElementById('run-source-info');
          if (srcEl && d.run_sources) {
            srcEl.textContent =
              d.run_sources.web_portal + ' web · ' +
              d.run_sources.desktop + ' desktop';
          }
        }
      })
      .catch(function () {});
  }

  function fetchTools() {
    fetch('/api/v1/tools/status', { credentials:'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d) renderToolStatusList(d);
        else {
          // Clear spinner
          var el = document.getElementById('tools-status-list');
          if (el && el.querySelector('.spinner, p')) {
            el.innerHTML = '<p class="text-muted text-sm" style="padding:0.75rem;">Tool status unavailable.</p>';
          }
        }
      })
      .catch(function () {
        var el = document.getElementById('tools-status-list');
        if (el) el.innerHTML = '<p class="text-muted text-sm" style="padding:0.75rem;">Could not load tool status.</p>';
      });
  }

  function fetchLTL() {
    fetch('/api/v1/ltl-properties', { credentials:'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && Array.isArray(d) && d.length) renderLTLTable(d); })
      .catch(function () {});
  }

  function fetchRecentRuns() {
    fetch('/api/v1/runs/recent?limit=50', { credentials:'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (runs) {
        if (Array.isArray(runs) && runs.length) {
          populateRunsTable(runs);
          // Also populate live feed from recent runs (first few)
          runs.slice(0, 10).reverse().forEach(function (r) {
            addFeedRow({
              tool: r.tool, status: r.status,
              filename: r.file, timestamp: r.timestamp,
              source: r.source
            });
          });
        }
      })
      .catch(function () {});
  }

  function refreshAll() {
    fetchState();
    fetchSummary();   // NEW — always pull from DB
    fetchTools();
    fetchLTL();
    fetchRecentRuns(); // NEW — fills table with web-portal + desktop runs
  }

  // ── Filter helpers (referenced in populateRunsTable) ─────────────────────

  var rows = Array.from(document.querySelectorAll('.run-row'));
  var runsCount = document.getElementById('runs-count');

  function applyFilters() {
    var tool   = ((document.getElementById('filter-tool')   || {}).value || '').toUpperCase();
    var status = ((document.getElementById('filter-status') || {}).value || '').toUpperCase();
    var file   = ((document.getElementById('filter-file')   || {}).value || '').toLowerCase().trim();
    var visible = 0;
    rows.forEach(function (row) {
      var match =
        (!tool   || row.dataset.tool   === tool)   &&
        (!status || row.dataset.status === status) &&
        (!file   || (row.dataset.file  || '').includes(file));
      row.style.display = match ? '' : 'none';
      if (match) visible++;
    });
    if (runsCount) runsCount.textContent = visible + ' run' + (visible !== 1 ? 's' : '');
  }

  document.addEventListener('DOMContentLoaded', function () {
    ['filter-tool','filter-status','filter-file'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('change', applyFilters);
      if (el) el.addEventListener('input',  applyFilters);
    });
  });

  // ── Real-time events ──────────────────────────────────────────────────────

  document.addEventListener('dg:state_update', function (e) {
    if (e.detail) {
      populateKPIs(e.detail);
      renderLTLTable(e.detail.ltl_results || []);
    }
  });

  document.addEventListener('dg:verification_complete', function (e) {
    if (e.detail) addFeedRow(e.detail);
    fetchTools();
    fetchLTL();
    fetchSummary();
    fetchRecentRuns();
  });

  // ── Init ──────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    refreshAll();
    setInterval(refreshAll, 15000);
  });

})();
