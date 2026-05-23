"""
api_v1_patch.py  —  Drop-in replacements / additions for api_v1.py

APPLY:  In web_portal/api_v1.py, replace the following route functions with
        the versions below.  All other routes remain unchanged.

Changes:
  1. api_state_current()      — merges DB summary so KPIs always show data
                                 even when verification_state.json is absent
  2. api_tools_status()       — merges last-known status from DB for each tool
  3. api_active_current()     — now includes web-portal-originated runs and
                                 inlines log content preview
  4. api_dashboard_summary()  — NEW  /api/v1/dashboard/summary
                                 holistic KPI data drawn only from DB
  5. api_recent_runs()        — NEW  /api/v1/runs/recent
                                 unified run list (desktop + web-portal) with
                                 source tag, log preview, and action links
  6. api_log_view()           — NEW  /api/v1/log-view/<audit_id>
                                 returns the stored log content for a run so
                                 the Logs page modal can render it
"""

from __future__ import annotations
import os, json, re, time
from pathlib import Path
from datetime import datetime

from flask import jsonify, request, session, current_app
from flask_login import login_required, current_user
from sqlalchemy import func

# ─── Blueprint import (already defined in api_v1.py) ───────────────────────
# from api_v1 import api_v1, load_state, save_state, _load_verification_content
# ─── DB import ──────────────────────────────────────────────────────────────
# from web_portal.audit_db import db, AuditHistory

# ═══════════════════════════════════════════════════════════════════════════
# 1. REPLACE  api_state_current
# ═══════════════════════════════════════════════════════════════════════════

@api_v1.route("/state/current")
def api_state_current():
    """
    Returns the global verification state, enriched with DB aggregates so
    the dashboard KPIs are always populated even without a desktop JSON file.
    """
    state = load_state()

    # ── Enrich with DB aggregates ──────────────────────────────────────────
    try:
        # Total states / transitions / depth from the most recent DB record
        latest = AuditHistory.query.order_by(
            AuditHistory.audit_date.desc()
        ).first()
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

        # LTL results — prefer state.json but fall back to last SPIN DB record
        if not state.get("ltl_results"):
            spin_row = AuditHistory.query.filter(
                AuditHistory.tool_used.ilike("SPIN")
            ).order_by(AuditHistory.audit_date.desc()).first()
            if spin_row and spin_row.ltl_properties:
                try:
                    props = json.loads(spin_row.ltl_properties)
                    if isinstance(props, list):
                        state["ltl_results"] = props
                    elif isinstance(props, str) and "ltl" in props:
                        # raw spec text — extract names
                        names = re.findall(r"ltl\s+(\w+)\s*\{", props)
                        state["ltl_results"] = [
                            {"name": n, "formula": "", "success": None, "status": "UNKNOWN"}
                            for n in names
                        ]
                except Exception:
                    pass
    except Exception:
        pass

    return jsonify(state)


# ═══════════════════════════════════════════════════════════════════════════
# 2. REPLACE  api_tools_status
# ═══════════════════════════════════════════════════════════════════════════

@api_v1.route("/tools/status")
def api_tools_status():
    """
    Returns per-tool status.  Merges binary availability check (from PATH)
    with last-known status from the DB so the dashboard tool list is
    populated even when verification_state.json has no data.
    """
    state = load_state()
    TOOLS = ["SPIN", "COQ", "LEAN", "CERTORA", "KANI", "PRUSTI", "CREUSOT", "VERUS"]

    try:
        from web_portal.verification_simulator import simulate as _sim  # noqa
        has_simulator = True
    except Exception:
        has_simulator = False

    # ── Pull last-known status per tool from DB ──────────────────────────
    db_status: dict[str, dict] = {}
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
        available = _check_tool_available(tool)
        # Global state has data from desktop JSON
        tool_data = state.get(tool.lower(), {})
        db_info   = db_status.get(tool, {})

        # Prefer DB data over stale JSON when JSON has no status
        json_status = tool_data.get("status", "")
        db_stat     = db_info.get("status", "UNKNOWN")
        last_status = json_status if json_status else db_stat

        last_run = tool_data.get("timestamp") or db_info.get("last_run", "")

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


# ═══════════════════════════════════════════════════════════════════════════
# 3. REPLACE  api_active_current
# ═══════════════════════════════════════════════════════════════════════════

@api_v1.route("/active/current")
@login_required
def api_active_current():
    """
    Returns the most recent audit for the logged-in user.
    Includes web-portal-originated runs (user_id set) as well as desktop
    synced runs (user_id NULL).  Also inlines a short log preview.
    """
    u_id    = current_user.get_id()
    user_id = int(u_id) if u_id else None

    latest = AuditHistory.query.filter(
        (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
    ).order_by(AuditHistory.audit_date.desc()).first()

    state = load_state()

    if latest:
        state["model_name"]     = latest.filename or state.get("model_name", "")
        state["active_tool"]    = latest.tool_used or state.get("active_tool", "SPIN")
        state["active_status"]  = latest.status or state.get("active_status", "")
        state["states_stored"]  = latest.states_explored or state.get("states_stored", 0)
        state["transitions"]    = latest.transitions    or state.get("transitions", 0)
        state["depth"]          = latest.depth_reached  or state.get("depth", 0)
        state["datetime"]       = (
            latest.audit_date.strftime("%Y-%m-%d %H:%M:%S")
            if latest.audit_date else state.get("datetime", "")
        )
        state["latest_audit_id"] = latest.id
        state["source"]          = "web_portal" if latest.user_id else "desktop"

        # Inline short log preview (first 400 chars)
        log_raw = latest.verification_output or ""
        state["log_preview"] = log_raw[:400] if log_raw else ""

        # LTL from this run's stored properties
        if latest.ltl_properties:
            try:
                props = json.loads(latest.ltl_properties)
                if isinstance(props, list) and props:
                    state["ltl_results"] = props
            except Exception:
                pass

    return jsonify(state)


# ═══════════════════════════════════════════════════════════════════════════
# 4. NEW  /api/v1/dashboard/summary
# ═══════════════════════════════════════════════════════════════════════════

@api_v1.route("/dashboard/summary")
@login_required
def api_dashboard_summary():
    """
    Holistic KPI data drawn entirely from the DB.
    Used by the dashboard when verification_state.json is absent or stale.
    Returns:
      total_runs, pass_runs, fail_runs, tools_used, latest_states,
      latest_transitions, latest_depth, latest_tool, latest_file,
      latest_date, ltl_pass, ltl_fail, run_sources (desktop / web_portal)
    """
    u_id    = current_user.get_id()
    user_id = int(u_id) if u_id else None

    try:
        base = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        )

        total = base.count()
        pass_c = base.filter(AuditHistory.status.ilike("PASS")).count()
        fail_c = base.filter(AuditHistory.status.ilike("FAIL")).count()

        # Distinct tools that have been run
        tools_q = db.session.query(
            func.distinct(AuditHistory.tool_used)
        ).filter(
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
                        if p.get("success") is True or p.get("status") == "VERIFIED":
                            ltl_pass += 1
                        elif p.get("success") is False or p.get("status") == "VIOLATED":
                            ltl_fail += 1
            except Exception:
                pass

        # Count by source
        web_count     = base.filter(AuditHistory.user_id.isnot(None)).count()
        desktop_count = base.filter(AuditHistory.user_id.is_(None)).count()

        return jsonify({
            "total_runs":       total,
            "pass_runs":        pass_c,
            "fail_runs":        fail_c,
            "tools_used":       tools_used,
            "tools_available":  len(tools_used),
            "latest_states":    latest.states_explored if latest else 0,
            "latest_trans":     latest.transitions    if latest else 0,
            "latest_depth":     latest.depth_reached  if latest else 0,
            "latest_tool":      latest.tool_used      if latest else "",
            "latest_file":      latest.filename       if latest else "",
            "latest_date":      latest.audit_date.strftime("%Y-%m-%d %H:%M:%S") if (latest and latest.audit_date) else "",
            "latest_audit_id":  latest.id             if latest else None,
            "ltl_pass":         ltl_pass,
            "ltl_fail":         ltl_fail,
            "run_sources": {
                "web_portal": web_count,
                "desktop":    desktop_count,
            },
        })
    except Exception as e:
        return jsonify({"error": str(e), "total_runs": 0}), 500


# ═══════════════════════════════════════════════════════════════════════════
# 5. NEW  /api/v1/runs/recent
# ═══════════════════════════════════════════════════════════════════════════

@api_v1.route("/runs/recent")
@login_required
def api_recent_runs():
    """
    Unified recent-runs list drawn from DB.
    Includes both desktop-synced records (user_id NULL) and web-portal
    records (user_id set), tagged by source.  Used by Active Run page
    and any other consumer that needs a run list.
    """
    u_id    = current_user.get_id()
    user_id = int(u_id) if u_id else None
    limit   = min(int(request.args.get("limit", 30)), 200)

    try:
        rows = AuditHistory.query.filter(
            (AuditHistory.user_id == user_id) | (AuditHistory.user_id.is_(None))
        ).order_by(AuditHistory.audit_date.desc()).limit(limit).all()

        result = []
        for r in rows:
            # Short log preview for tooltip / quick view
            log_raw  = r.verification_output or ""
            preview  = log_raw[:300].strip() if log_raw else ""

            # LTL quick counts
            ltl_pass = ltl_fail = 0
            if r.ltl_properties:
                try:
                    props = json.loads(r.ltl_properties)
                    if isinstance(props, list):
                        for p in props:
                            if p.get("success") is True or p.get("status") == "VERIFIED":
                                ltl_pass += 1
                            else:
                                ltl_fail += 1
                except Exception:
                    pass

            result.append({
                "id":          r.id,
                "timestamp":   r.audit_date.isoformat() if r.audit_date else "",
                "date_short":  r.audit_date.strftime("%Y-%m-%d %H:%M") if r.audit_date else "",
                "tool":        (r.tool_used or "").upper(),
                "file":        r.filename or "unknown",
                "status":      (r.status or "UNKNOWN").upper(),
                "states":      r.states_explored or 0,
                "transitions": r.transitions    or 0,
                "depth":       r.depth_reached  or 0,
                "error_msg":   r.vulnerabilities_found or "",
                "ltl_pass":    ltl_pass,
                "ltl_fail":    ltl_fail,
                "log_preview": preview,
                "source":      "web_portal" if r.user_id else "desktop",
                "has_trace":   bool(r.report_path or r.trace_data),
                "audit_url":   f"/counterexample/{r.id}",
                "trace_url":   f"/trace/{r.id}",
            })

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "runs": []}), 500


# ═══════════════════════════════════════════════════════════════════════════
# 6. NEW  /api/v1/log-view/<audit_id>
# ═══════════════════════════════════════════════════════════════════════════

@api_v1.route("/log-view/<audit_id>")
@login_required
def api_log_view(audit_id):
    """
    Returns the full stored log / verification output for a single audit
    record.  Used by the Logs page modal so web-portal runs render their
    log content even though no file exists on disk.
    """
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
        # If it looks like a file path, try to read it
        if content and "\n" not in content and len(content) < 600:
            try:
                p = Path(content)
                if p.exists():
                    content = p.read_text(encoding="utf-8", errors="replace")[:100000]
            except Exception:
                pass

        # LTL properties
        ltl = []
        if row.ltl_properties:
            try:
                ltl = json.loads(row.ltl_properties)
                if not isinstance(ltl, list):
                    ltl = []
            except Exception:
                pass

        return jsonify({
            "id":        row.id,
            "tool":      row.tool_used or "",
            "filename":  row.filename  or "",
            "status":    row.status    or "",
            "date":      row.audit_date.strftime("%Y-%m-%d %H:%M:%S") if row.audit_date else "",
            "states":    row.states_explored or 0,
            "depth":     row.depth_reached   or 0,
            "content":   content,
            "ltl":       ltl,
            "source":    "web_portal" if row.user_id else "desktop",
        })
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid ID: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
