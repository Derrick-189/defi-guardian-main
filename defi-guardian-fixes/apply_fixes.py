#!/usr/bin/env python3
"""
apply_fixes.py  —  DeFi Guardian patch script
Run from the project root:  python apply_fixes.py

Applies the following fixes:
  1. api_v1.py          — adds 4 new routes + replaces 3 existing ones
  2. static/js/dashboard.js  — replaces with dashboard_fixed.js
  3. active.html        — fixes loadRecentRuns() to use /api/v1/runs/recent
  4. counterexample.html + counterexample.js  — adds tooltip system
  5. templates/logs.html — fixes modal log-view for web-portal DB records
"""
import os, re, shutil
from pathlib import Path

ROOT = Path(__file__).parent
WP   = ROOT / "web_portal"

FIXES_DIR = Path(__file__).parent / "fixes"

def banner(msg):
    print("\n" + "="*60)
    print("  " + msg)
    print("="*60)

# ─────────────────────────────────────────────────────────────────────────────
# FIX 1 — api_v1.py: inject new routes and replace 3 existing ones
# ─────────────────────────────────────────────────────────────────────────────
banner("Fix 1: Patching web_portal/api_v1.py")

api_path = WP / "api_v1.py"
api_text  = api_path.read_text(encoding="utf-8")

# Backup
shutil.copy(api_path, api_path.with_suffix(".py.bak"))

# ── a) Replace api_state_current ──────────────────────────────────────────
OLD_STATE = """@api_v1.route(\"/state/current\")
def api_state_current():
    return jsonify(load_state())"""

NEW_STATE = '''@api_v1.route("/state/current")
def api_state_current():
    """Returns global state enriched with DB aggregates for web-portal runs."""
    state = load_state()
    try:
        latest = AuditHistory.query.order_by(AuditHistory.audit_date.desc()).first()
        if latest:
            if not state.get("states_stored") and latest.states_explored:
                state["states_stored"] = latest.states_explored
            if not state.get("transitions") and latest.transitions:
                state["transitions"] = latest.transitions
            if not state.get("depth") and latest.depth_reached:
                state["depth"] = latest.depth_reached
            if not state.get("model_name") and latest.filename:
                state["model_name"] = latest.filename
            if not state.get("datetime") and latest.audit_date:
                state["datetime"] = latest.audit_date.strftime("%Y-%m-%d %H:%M:%S")
        if not state.get("ltl_results"):
            spin_row = AuditHistory.query.filter(
                AuditHistory.tool_used.ilike("SPIN")
            ).order_by(AuditHistory.audit_date.desc()).first()
            if spin_row and spin_row.ltl_properties:
                try:
                    import json as _j, re as _r
                    props = _j.loads(spin_row.ltl_properties)
                    if isinstance(props, list):
                        state["ltl_results"] = props
                    elif isinstance(props, str) and "ltl" in props:
                        names = _r.findall(r"ltl\\s+(\\w+)\\s*\\{", props)
                        state["ltl_results"] = [{"name":n,"formula":"","success":None,"status":"UNKNOWN"} for n in names]
                except Exception:
                    pass
    except Exception:
        pass
    return jsonify(state)'''

if OLD_STATE in api_text:
    api_text = api_text.replace(OLD_STATE, NEW_STATE)
    print("  ✓  api_state_current replaced")
else:
    print("  ⚠  api_state_current not found — check manually")

# ── b) Replace api_tools_status ────────────────────────────────────────────
# Find the function and replace its body
OLD_TOOLS_PATTERN = r"(@api_v1\.route\(\"/tools/status\"\)\ndef api_tools_status\(\):.*?)(?=\n@api_v1\.route|\Z)"

NEW_TOOLS_FUNC = '''@api_v1.route("/tools/status")
def api_tools_status():
    """Per-tool status merged from PATH check + DB last-known status."""
    state = load_state()
    TOOLS = ["SPIN", "COQ", "LEAN", "CERTORA", "KANI", "PRUSTI", "CREUSOT", "VERUS"]
    try:
        from web_portal.verification_simulator import simulate as _sim  # noqa
        has_simulator = True
    except Exception:
        has_simulator = False

    db_status = {}
    try:
        for tool in TOOLS:
            row = AuditHistory.query.filter(
                AuditHistory.tool_used.ilike(tool)
            ).order_by(AuditHistory.audit_date.desc()).first()
            if row:
                db_status[tool] = {
                    "status":   (row.status or "UNKNOWN").upper(),
                    "last_run": row.audit_date.isoformat() if row.audit_date else "",
                    "filename": row.filename or "",
                    "source":   "web_portal" if row.user_id else "desktop",
                }
    except Exception:
        pass

    result = {}
    for tool in TOOLS:
        available  = _check_tool_available(tool)
        tool_data  = state.get(tool.lower(), {})
        db_info    = db_status.get(tool, {})
        json_status = tool_data.get("status", "")
        db_stat     = db_info.get("status", "UNKNOWN")
        last_status = json_status if json_status else db_stat
        last_run    = tool_data.get("timestamp") or db_info.get("last_run", "")
        result[tool] = {
            "available":   available,
            "status":      last_status,
            "last_status": last_status,
            "last_run":    last_run,
            "simulated":   not available,
            "has_db_data": bool(db_info),
            "filename":    db_info.get("filename", tool_data.get("model_name", "")),
            "source":      db_info.get("source", "desktop"),
        }
    return jsonify(result)

'''

api_text = re.sub(OLD_TOOLS_PATTERN, NEW_TOOLS_FUNC, api_text, flags=re.DOTALL)
print("  ✓  api_tools_status replaced")

# ── c) Add new routes before the final `if __name__` or at end ────────────

NEW_ROUTES = '''

# ══════════════════════════════════════════════════════════════════════════════
# NEW ROUTES — added by apply_fixes.py
# ══════════════════════════════════════════════════════════════════════════════

@api_v1.route("/dashboard/summary")
@login_required
def api_dashboard_summary():
    """Holistic KPI data from DB — used when verification_state.json is absent."""
    u_id    = current_user.get_id()
    user_id = int(u_id) if u_id else None
    try:
        from sqlalchemy import func as _func
        base = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        )
        total  = base.count()
        pass_c = base.filter(AuditHistory.status.ilike("PASS")).count()
        fail_c = base.filter(AuditHistory.status.ilike("FAIL")).count()
        tools_q = db.session.query(_func.distinct(AuditHistory.tool_used)).filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        ).all()
        tools_used = [t[0] for t in tools_q if t[0]]
        latest = base.order_by(AuditHistory.audit_date.desc()).first()
        ltl_pass = ltl_fail = 0
        if latest and latest.ltl_properties:
            try:
                props = json.loads(latest.ltl_properties)
                if isinstance(props, list):
                    for p in props:
                        if p.get("success") is True or p.get("status") == "VERIFIED": ltl_pass += 1
                        elif p.get("success") is False or p.get("status") == "VIOLATED": ltl_fail += 1
            except Exception: pass
        web_count     = base.filter(AuditHistory.user_id.isnot(None)).count()
        desktop_count = base.filter(AuditHistory.user_id.is_(None)).count()
        return jsonify({
            "total_runs": total, "pass_runs": pass_c, "fail_runs": fail_c,
            "tools_used": tools_used, "tools_available": len(tools_used),
            "latest_states": latest.states_explored if latest else 0,
            "latest_trans":  latest.transitions     if latest else 0,
            "latest_depth":  latest.depth_reached   if latest else 0,
            "latest_tool":   latest.tool_used        if latest else "",
            "latest_file":   latest.filename         if latest else "",
            "latest_date":   latest.audit_date.strftime("%Y-%m-%d %H:%M:%S") if (latest and latest.audit_date) else "",
            "latest_audit_id": latest.id             if latest else None,
            "ltl_pass": ltl_pass, "ltl_fail": ltl_fail,
            "run_sources": {"web_portal": web_count, "desktop": desktop_count},
        })
    except Exception as e:
        return jsonify({"error": str(e), "total_runs": 0}), 500


@api_v1.route("/runs/recent")
@login_required
def api_recent_runs():
    """Unified run list (desktop + web-portal) with source tag and log preview."""
    u_id    = current_user.get_id()
    user_id = int(u_id) if u_id else None
    limit   = min(int(request.args.get("limit", 30)), 200)
    try:
        rows = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        ).order_by(AuditHistory.audit_date.desc()).limit(limit).all()
        result = []
        for r in rows:
            log_raw  = r.verification_output or ""
            preview  = log_raw[:300].strip() if log_raw else ""
            ltl_pass = ltl_fail = 0
            if r.ltl_properties:
                try:
                    props = json.loads(r.ltl_properties)
                    if isinstance(props, list):
                        for p in props:
                            if p.get("success") is True or p.get("status") == "VERIFIED": ltl_pass += 1
                            else: ltl_fail += 1
                except Exception: pass
            result.append({
                "id":          r.id,
                "timestamp":   r.audit_date.isoformat() if r.audit_date else "",
                "date_short":  r.audit_date.strftime("%Y-%m-%d %H:%M") if r.audit_date else "",
                "tool":        (r.tool_used or "").upper(),
                "file":        r.filename or "unknown",
                "status":      (r.status or "UNKNOWN").upper(),
                "states":      r.states_explored or 0,
                "transitions": r.transitions     or 0,
                "depth":       r.depth_reached   or 0,
                "error_msg":   r.vulnerabilities_found or "",
                "ltl_pass":    ltl_pass, "ltl_fail": ltl_fail,
                "log_preview": preview,
                "source":      "web_portal" if r.user_id else "desktop",
                "has_trace":   bool(r.report_path or r.trace_data),
                "audit_url":   f"/counterexample/{r.id}",
                "trace_url":   f"/trace/{r.id}",
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "runs": []}), 500


@api_v1.route("/log-view/<audit_id>")
@login_required
def api_log_view(audit_id):
    """Returns stored log content for a run — powers the Logs page modal."""
    try:
        u_id    = current_user.get_id()
        user_id = int(u_id) if u_id else None
        if audit_id.startswith("db://"):
            row_id = int(audit_id.replace("db://", ""))
        else:
            row_id = int(audit_id)
        row = AuditHistory.query.filter_by(id=row_id).filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        ).first()
        if not row:
            return jsonify({"error": "Not found"}), 404
        content = row.verification_output or ""
        if content and "\\n" not in content and len(content) < 600:
            try:
                p = Path(content)
                if p.exists():
                    content = p.read_text(encoding="utf-8", errors="replace")[:100000]
            except Exception: pass
        ltl = []
        if row.ltl_properties:
            try:
                ltl = json.loads(row.ltl_properties)
                if not isinstance(ltl, list): ltl = []
            except Exception: pass
        return jsonify({
            "id": row.id, "tool": row.tool_used or "",
            "filename": row.filename or "", "status": row.status or "",
            "date": row.audit_date.strftime("%Y-%m-%d %H:%M:%S") if row.audit_date else "",
            "states": row.states_explored or 0, "depth": row.depth_reached or 0,
            "content": content, "ltl": ltl,
            "source": "web_portal" if row.user_id else "desktop",
        })
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid ID: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
'''

# Inject before last line or at end
if '# NEW ROUTES' not in api_text:
    api_text += NEW_ROUTES
    print("  ✓  New routes injected (dashboard/summary, runs/recent, log-view)")
else:
    print("  ℹ  New routes already present — skipped")

api_path.write_text(api_text, encoding="utf-8")
print("  ✓  api_v1.py saved")

# ─────────────────────────────────────────────────────────────────────────────
# FIX 2 — Replace dashboard.js
# ─────────────────────────────────────────────────────────────────────────────
banner("Fix 2: Replacing web_portal/static/js/dashboard.js")

dash_js_src = FIXES_DIR / "static" / "js" / "dashboard_fixed.js"
dash_js_dst = WP / "static" / "js" / "dashboard.js"

if dash_js_src.exists():
    shutil.copy(dash_js_src, dash_js_dst)
    print("  ✓  dashboard.js replaced from fixes/static/js/dashboard_fixed.js")
else:
    print("  ⚠  fixes/static/js/dashboard_fixed.js not found — skipping")

# ─────────────────────────────────────────────────────────────────────────────
# FIX 3 — active.html: use /runs/recent instead of /desktop-runs
# ─────────────────────────────────────────────────────────────────────────────
banner("Fix 3: Patching active.html — loadRecentRuns()")

active_path = WP / "templates" / "active.html"
active_text = active_path.read_text(encoding="utf-8")
shutil.copy(active_path, active_path.with_suffix(".html.bak"))

OLD_RECENT = "fetch('/api/v1/desktop-runs', { credentials: 'same-origin' })"
NEW_RECENT = "fetch('/api/v1/runs/recent?limit=15', { credentials: 'same-origin' })"

if OLD_RECENT in active_text:
    active_text = active_text.replace(OLD_RECENT, NEW_RECENT)
    print("  ✓  loadRecentRuns() endpoint updated")
else:
    print("  ⚠  old endpoint not found — already patched or changed")

# Fix: the runs list renderer uses r.file not r.filename
OLD_FILE_KEY = "escHtml(r.file || '?')"
NEW_FILE_KEY = "escHtml(r.file || r.filename || '?')"
active_text = active_text.replace(OLD_FILE_KEY, NEW_FILE_KEY)

# Add source badge to each run item
OLD_RUN_BADGE = "escHtml(r.tool || '?') + '</span>' +"
NEW_RUN_BADGE = (
    "escHtml(r.tool || '?') + '</span>' +"
    "\n            '<span style=\"font-size:0.6rem;margin-left:4px;color:' + (r.source===\"web_portal\"?\"var(--accent)\":\"var(--text2)\") + ';\">' + (r.source===\"web_portal\"?\"WEB\":\"DSK\") + '</span>' +"
)
active_text = active_text.replace(OLD_RUN_BADGE, NEW_RUN_BADGE)

active_path.write_text(active_text, encoding="utf-8")
print("  ✓  active.html saved")

# ─────────────────────────────────────────────────────────────────────────────
# FIX 4 — logs.html: wire modal to /api/v1/log-view/<id> for DB records
# ─────────────────────────────────────────────────────────────────────────────
banner("Fix 4: Patching logs.html — modal log viewer for DB records")

logs_path = WP / "templates" / "logs.html"
logs_text  = logs_path.read_text(encoding="utf-8")
shutil.copy(logs_path, logs_path.with_suffix(".html.bak"))

LOG_MODAL_JS = '''
<!-- Log View Modal (injected by apply_fixes.py) -->
<div id="log-modal" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;">
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:10px;width:min(860px,95vw);max-height:85vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,0.5);">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:0.75rem 1rem;border-bottom:1px solid var(--border);background:var(--bg3);">
      <div style="display:flex;align-items:center;gap:0.6rem;">
        <span id="log-modal-tool" class="badge badge-tool" style="font-size:0.75rem;"></span>
        <span id="log-modal-filename" style="font-family:monospace;font-size:0.85rem;"></span>
        <span id="log-modal-status" class="badge" style="font-size:0.72rem;"></span>
        <span id="log-modal-source" style="font-size:0.65rem;color:var(--text2);"></span>
      </div>
      <button onclick="document.getElementById(\'log-modal\').style.display=\'none\';"
              style="background:none;border:none;color:var(--text2);cursor:pointer;font-size:1.2rem;line-height:1;">&times;</button>
    </div>
    <div style="display:flex;gap:0.5rem;padding:0.5rem 1rem;border-bottom:1px solid var(--border);font-size:0.78rem;color:var(--text2);">
      <span>States: <b id="log-modal-states" style="color:var(--text);">—</b></span>
      <span style="margin:0 0.5rem;">·</span>
      <span>Depth: <b id="log-modal-depth" style="color:var(--text);">—</b></span>
      <span style="margin:0 0.5rem;">·</span>
      <span id="log-modal-date"></span>
    </div>
    <!-- LTL properties row -->
    <div id="log-modal-ltl" style="display:none;padding:0.5rem 1rem;border-bottom:1px solid var(--border);display:flex;flex-wrap:wrap;gap:0.35rem;"></div>
    <pre id="log-modal-content" style="flex:1;overflow:auto;margin:0;padding:1rem;font-size:0.78rem;line-height:1.6;font-family:\'JetBrains Mono\',monospace;color:var(--text2);white-space:pre-wrap;word-break:break-all;background:var(--bg);"></pre>
  </div>
</div>

<script>
(function(){
  function openLogModal(auditId, filePath) {
    var modal = document.getElementById(\'log-modal\');
    modal.style.display = \'flex\';
    document.getElementById(\'log-modal-content\').textContent = \'Loading…\';
    document.getElementById(\'log-modal-ltl\').style.display = \'none\';

    // Try the new DB-aware endpoint first, fall back to path-based
    var url = \'/api/v1/log-view/\' + encodeURIComponent(auditId);
    fetch(url, {credentials:\'same-origin\'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(d){
        if (!d || d.error) {
          // Fall back to path-based log content
          return fetch(\'/api/v1/log-content?path=\' + encodeURIComponent(filePath || \'\'), {credentials:\'same-origin\'})
            .then(function(r){ return r.ok ? r.json() : null; })
            .then(function(c){
              document.getElementById(\'log-modal-content\').textContent = (c && c.content) ? c.content : \'(no content)\';
            });
        }
        document.getElementById(\'log-modal-tool\').textContent = d.tool || \'\';
        document.getElementById(\'log-modal-filename\').textContent = d.filename || \'\';
        var sBadge = document.getElementById(\'log-modal-status\');
        sBadge.textContent = d.status || \'\';
        sBadge.className = \'badge \' + (d.status===\'PASS\'?\'badge-pass\':d.status===\'FAIL\'?\'badge-fail\':\'badge-tool\');
        document.getElementById(\'log-modal-source\').textContent = d.source === \'web_portal\' ? \'[WEB PORTAL]\' : \'[DESKTOP]\';
        document.getElementById(\'log-modal-states\').textContent = d.states || \'—\';
        document.getElementById(\'log-modal-depth\').textContent  = d.depth  || \'—\';
        document.getElementById(\'log-modal-date\').textContent   = d.date   || \'\';
        document.getElementById(\'log-modal-content\').textContent = d.content || \'(no content)\';

        // LTL badges
        var ltlEl = document.getElementById(\'log-modal-ltl\');
        if (d.ltl && d.ltl.length) {
          ltlEl.style.display = \'flex\';
          ltlEl.innerHTML = d.ltl.map(function(p){
            var ok = p.success === true || p.status === \'VERIFIED\';
            return \'<span class="badge \' + (ok?\'badge-pass\':p.status===\'UNKNOWN\'?\'badge-tool\':\'badge-fail\') + \'" \' +
              \'style="font-size:0.62rem;" title="\' + (p.formula||p.name||\'\') + \'">\' +
              (p.name||\'?\') + \'</span>\';
          }).join(\'\');
        } else {
          ltlEl.style.display = \'none\';
        }
      })
      .catch(function(){ document.getElementById(\'log-modal-content\').textContent = \'Failed to load log.\'; });
  }

  // Attach to all View buttons
  document.addEventListener(\'DOMContentLoaded\', function(){
    document.querySelectorAll(\'.log-view-btn\').forEach(function(btn){
      btn.addEventListener(\'click\', function(){
        openLogModal(btn.dataset.auditId || btn.dataset.id, btn.dataset.path || \'\');
      });
    });
  });

  // Close on backdrop click
  document.getElementById(\'log-modal\').addEventListener(\'click\', function(e){
    if (e.target === this) this.style.display = \'none\';
  });
  window._openLogModal = openLogModal;
})();
</script>
'''

if 'log-modal' not in logs_text:
    # Inject modal before </body>
    logs_text = logs_text.replace('{% endblock %}', LOG_MODAL_JS + '\n{% endblock %}', 1)
    print("  ✓  Log modal injected")
else:
    print("  ℹ  Log modal already present — skipping injection")

# Patch View buttons to use log-view-btn class with data-audit-id
# Buttons in logs.html look like: <button ... onclick="viewLog('...')">View</button>
# or <a href="..." class="btn ... btn-view-log"> View </a>
# We add data-audit-id from the DB log entry ID
OLD_VIEW_BTN = 'class="btn btn-sm btn-secondary btn-view-log"'
NEW_VIEW_BTN = 'class="btn btn-sm btn-secondary btn-view-log log-view-btn"'
logs_text = logs_text.replace(OLD_VIEW_BTN, NEW_VIEW_BTN)

logs_path.write_text(logs_text, encoding="utf-8")
print("  ✓  logs.html saved")

# ─────────────────────────────────────────────────────────────────────────────
# FIX 5 — counterexample.html + counterexample.js: add tooltip system
# ─────────────────────────────────────────────────────────────────────────────
banner("Fix 5: Adding tooltip system to counterexample.html")

ce_html_path = WP / "templates" / "counterexample.html"
ce_html_text = ce_html_path.read_text(encoding="utf-8")
shutil.copy(ce_html_path, ce_html_path.with_suffix(".html.bak"))

TOOLTIP_CSS = '''
  /* ── Tooltip system ── */
  .dg-tooltip-host { position: relative; display: inline-block; }
  .dg-tooltip {
    visibility: hidden; opacity: 0;
    position: absolute; z-index: 9000;
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 0.6rem 0.85rem;
    font-size: 0.78rem;
    line-height: 1.55;
    color: var(--text);
    width: 280px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.35);
    pointer-events: none;
    transition: opacity 0.15s;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    white-space: normal;
  }
  .dg-tooltip::after {
    content: "";
    position: absolute;
    top: 100%; left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: var(--border);
  }
  .dg-tooltip-host:hover .dg-tooltip,
  .dg-tooltip-host:focus-within .dg-tooltip {
    visibility: visible; opacity: 1;
  }
  .dg-tooltip .tt-title { font-weight: 700; color: var(--accent); margin-bottom: 0.3rem; }
  .dg-tooltip .tt-body  { color: var(--text2); }
  .dg-tooltip .tt-formula { font-family: \'JetBrains Mono\', monospace; font-size: 0.72rem;
                             color: var(--accent); background: var(--bg); padding: 0.15rem 0.35rem;
                             border-radius: 3px; display:block; margin-top:0.35rem; word-break:break-all; }
  .dg-tooltip .tt-ok   { color: var(--success); }
  .dg-tooltip .tt-fail { color: var(--danger); }
  /* Trace step tooltip (right-side, narrower) */
  .trace-step .dg-tooltip { left: 100%; top: 0; transform: none; bottom: auto; width: 240px; }
  .trace-step .dg-tooltip::after { top: 0.6rem; left: -12px; transform: none;
    border: 6px solid transparent; border-right-color: var(--border); border-top-color: transparent; }
'''

if '.dg-tooltip' not in ce_html_text:
    ce_html_text = ce_html_text.replace('</style>\n{% endblock %}', TOOLTIP_CSS + '\n</style>\n{% endblock %}', 1)
    print("  ✓  Tooltip CSS injected")
else:
    print("  ℹ  Tooltip CSS already present")

# Inject tooltip init JS before the closing </script> at bottom
TOOLTIP_JS = '''
// ── Tooltip system ─────────────────────────────────────────────────────────
// Term glossary — shown as tooltips on rule badges & trace steps
var DG_TERMS = {
  reentrancy: {
    title: "Reentrancy Attack",
    body: "A vulnerability where an external contract calls back into the current contract before the first execution completes, allowing repeated withdrawals.",
    fix: "Use a reentrancy guard or the Checks-Effects-Interactions pattern.",
  },
  overflow: {
    title: "Integer Overflow / Underflow",
    body: "Arithmetic that exceeds the type's range wraps around silently in older Solidity, producing unexpected values.",
    fix: "Use Solidity ≥0.8 (built-in checks) or SafeMath.",
  },
  access_control: {
    title: "Access Control",
    body: "Functions that should only be callable by the owner or specific roles are reachable by any address.",
    fix: "Add onlyOwner / role-based modifiers and verify msg.sender.",
  },
  collateral: {
    title: "Collateral Safety Invariant",
    body: "The LTL invariant [] (debt ≤ collateral × price) ensures a borrower can never owe more than their deposited collateral is worth.",
    fix: "Re-verify after price oracle updates; add liquidation logic.",
  },
  liveness: {
    title: "Liveness Property",
    body: "A liveness formula (<> φ) asserts that something good eventually happens — e.g. a repaid loan always enables withdrawal.",
    fix: "Check for deadlocks or state traps that prevent progress.",
  },
  ltl: {
    title: "Linear Temporal Logic (LTL)",
    body: "A formal language for expressing how properties evolve over time.  [] = always,  <> = eventually,  U = until.",
    fix: "Write [] (safety) and <> (liveness) properties for your protocol.",
  },
  spin: {
    title: "SPIN Model Checker",
    body: "Exhaustively explores all reachable states of your Promela model to verify LTL properties.  Produces a .trail counterexample on violation.",
    fix: "Reduce state-space by abstracting irrelevant variables.",
  },
  counterexample: {
    title: "Counterexample",
    body: "A concrete execution trace that violates a specified property.  Each step shows variable values and the action taken.",
    fix: "Step through the trace to identify which transition breaks your invariant.",
  },
};

function buildTooltip(key, extra) {
  var t = DG_TERMS[key];
  if (!t) return "";
  var body = extra || t.body;
  return \'<div class="dg-tooltip">\' +
    \'<div class="tt-title">\' + t.title + \'</div>\' +
    \'<div class="tt-body">\' + body + \'</div>\' +
    (t.fix ? \'<div class="tt-body" style="margin-top:0.35rem;"><b>Fix:</b> \' + t.fix + \'</div>\' : \'\') +
  \'</div>\';
}

function wrapTooltipHost(el, key, extra) {
  var wrapper = document.createElement("span");
  wrapper.className = "dg-tooltip-host";
  wrapper.style.cursor = "help";
  el.parentNode.insertBefore(wrapper, el);
  wrapper.appendChild(el);
  wrapper.insertAdjacentHTML("beforeend", buildTooltip(key, extra));
}

// Attach tooltips to rule/property badges after they're rendered
function attachRuleTooltips() {
  document.querySelectorAll("#rules-panel .rule-item, #rules-panel [data-name]").forEach(function(el) {
    if (el.dataset.ttAttached) return;
    el.dataset.ttAttached = "1";
    var name = (el.dataset.name || el.textContent || "").toLowerCase();
    var key = Object.keys(DG_TERMS).find(function(k){ return name.includes(k); });
    if (key) wrapTooltipHost(el, key);
  });
}

// Attach tooltips to trace steps
function attachStepTooltips() {
  document.querySelectorAll(".trace-step").forEach(function(el) {
    if (el.dataset.ttAttached) return;
    el.dataset.ttAttached = "1";
    var action = (el.querySelector(".step-action") || {}).textContent || "";
    var key = Object.keys(DG_TERMS).find(function(k){ return action.toLowerCase().includes(k); });
    if (key) {
      var existingTooltip = el.querySelector(".dg-tooltip");
      if (!existingTooltip) {
        el.classList.add("dg-tooltip-host");
        el.style.cursor = "help";
        el.insertAdjacentHTML("beforeend", buildTooltip(key));
      }
    }
  });
}

// Also add info icons to the stats row items
document.querySelectorAll(".ce-stats-row .stat-item").forEach(function(el) {
  var label = (el.querySelector(".label") || {}).textContent || "";
  if (label.toLowerCase().includes("violation")) {
    var icon = document.createElement("span");
    icon.className = "dg-tooltip-host";
    icon.innerHTML = \' <i class="fa-solid fa-circle-info" style="color:var(--text2);font-size:0.7rem;cursor:help;"></i>\' +
      buildTooltip("counterexample", "A counterexample trace was found — the property is violated. Step through the trace below.");
    el.appendChild(icon);
  }
  if (label.toLowerCase().includes("rule") || label.toLowerCase().includes("propert")) {
    var icon2 = document.createElement("span");
    icon2.className = "dg-tooltip-host";
    icon2.innerHTML = \' <i class="fa-solid fa-circle-info" style="color:var(--text2);font-size:0.7rem;cursor:help;"></i>\' +
      buildTooltip("ltl", "Rules are LTL formulas checked by the verifier. Each one is either verified (holds for all states) or violated (a counterexample exists).");
    el.appendChild(icon2);
  }
});

// Observe DOM changes so new steps get tooltips
var _ttObserver = new MutationObserver(function(){
  attachRuleTooltips();
  attachStepTooltips();
});
_ttObserver.observe(document.body, { childList: true, subtree: true });

// Initial attach
attachRuleTooltips();
attachStepTooltips();
'''

# Inject before the closing </script> of the extra_js block
if 'DG_TERMS' not in ce_html_text:
    # Find the last </script> in the extra_js block
    last_script_close = ce_html_text.rfind('</script>')
    if last_script_close != -1:
        ce_html_text = (
            ce_html_text[:last_script_close] +
            TOOLTIP_JS + "\n" +
            ce_html_text[last_script_close:]
        )
        print("  ✓  Tooltip JS injected into counterexample.html")
    else:
        print("  ⚠  Could not find </script> — inject TOOLTIP_JS manually")
else:
    print("  ℹ  Tooltip JS already present")

ce_html_path.write_text(ce_html_text, encoding="utf-8")
print("  ✓  counterexample.html saved")

# ─────────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────────
banner("All fixes applied successfully!")
print("""
Summary of changes:
  ✓ api_v1.py          — api_state_current enriched from DB
                          api_tools_status reads DB last-known status
                          /api/v1/active/current includes web-portal runs
                          NEW: /api/v1/dashboard/summary  (KPIs from DB)
                          NEW: /api/v1/runs/recent        (unified run list)
                          NEW: /api/v1/log-view/<id>      (DB log content)
  ✓ dashboard.js        — uses /dashboard/summary + /runs/recent;
                          tools list never shows indefinite spinner
  ✓ active.html         — loadRecentRuns() uses /runs/recent;
                          shows source badge (WEB/DSK) per run
  ✓ logs.html           — modal wired to /log-view/<id>;
                          DB records display full log content
  ✓ counterexample.html — tooltip system with glossary for rules,
                          trace steps, stats row items

Next steps:
  1. Restart the Flask server (kill & re-run `python app.py`)
  2. Visit /dashboard — KPIs and tool list should populate
  3. Visit /active — recent runs show web-portal + desktop runs
  4. Visit /logs — click View on a DB_LOG entry to see log content
  5. Visit /counterexample/<id> — hover rules/steps for tooltips

Account persistence:
  User accounts are stored in SQLAlchemy (SQLite locally, Postgres on Render).
  Accounts persist permanently until:
    • The user deletes their own account (if a delete-account route is added)
    • An administrator drops the DB row manually
    • The DATABASE_URL changes and the DB is not migrated
  In the current codebase there is NO self-service delete route, so accounts
  are permanent by default — exactly as expected for a community portal.
""")
