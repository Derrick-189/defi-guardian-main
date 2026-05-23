# DeFi Guardian — Bug Fixes Package

## Issues fixed

### 1. Verification & Account Dashboards not loading (web portal)
**Root cause:** The dashboard KPIs and tool-status list fetched data only
from `verification_state.json` (written by the desktop app). When the web
portal runs verifications, that file stays empty, so the UI showed `—` for
every KPI and "Loading tool status…" indefinitely.

**Fix:**
- `api_state_current()` now enriches the JSON with DB aggregates.
- New endpoint `GET /api/v1/dashboard/summary` returns KPIs directly from
  the database (works for web-portal runs with no JSON file).
- `api_tools_status()` merges last-known per-tool status from the DB.
- `dashboard.js` calls both endpoints and uses whichever has data.

### 2. Logs & Reports not rendering for web-portal runs
**Root cause:** Web-portal verifications store log content in the DB
(`verification_output` column). The logs page listed `DB_LOG_*` entries
but the View button had no way to load their content (there was no modal).

**Fix:**
- New endpoint `GET /api/v1/log-view/<audit_id>` returns the stored
  log content, LTL badges, and metadata for any DB row.
- `logs_modal_patch.html` injects a full-featured modal (search, copy,
  word-wrap, LTL badges, source badge WEB/DESKTOP).
- The modal reads the `data-audit-id` attribute on each View button.

### 3. Active Run not showing latest runs for web-portal
**Root cause:** The Recent Runs list on the Active page fetched
`/api/v1/desktop-runs` which filtered for rows with `user_id == NULL`
(desktop-synced only). Web-portal runs have `user_id` set.

**Fix:**
- New endpoint `GET /api/v1/runs/recent` returns a unified list of
  desktop + web-portal runs tagged with `source: "web_portal"|"desktop"`.
- `active.html` now calls `/api/v1/runs/recent` and shows WEB/DSK badges.

### 4. Counterexample analysis tooltip system
**Root cause:** The counterexample page had no hover explanations for the
formal-verification terminology, making it hard for non-experts to understand
what they were looking at.

**Fix:** A full tooltip system added to `counterexample.html`:
- Hover over **rule/property badges** → explanation of the LTL property.
- Hover over **trace steps** → explanation of the action (reentrancy,
  overflow, access control, etc.).
- Hover over **stats row** Violations / Rules icons → brief glossary.
- Glossary covers: reentrancy, overflow, access_control, collateral,
  liveness, ltl, spin, counterexample.

---

## How to apply

### Option A — Automated patch script (recommended)

```bash
# 1. Copy the fixes/ folder into your project root
cp -r fixes  ~/defi-guardian-main/fixes

# 2. Copy apply_fixes.py into your project root
cp apply_fixes.py  ~/defi-guardian-main/

# 3. Run from the project root
cd ~/defi-guardian-main
python apply_fixes.py
```

The script creates `.bak` backups of every file it modifies.

### Option B — Manual drop-in

| File to replace / add | Source in this package |
|---|---|
| `web_portal/static/js/dashboard.js` | `web_portal/static/js/dashboard_fixed.js` |
| Append to `web_portal/api_v1.py` | `web_portal/api_v1_patch.py` (see instructions inside) |
| Append before `{% endblock %}` in `logs.html` | `web_portal/templates/logs_modal_patch.html` |
| Append tooltip CSS+JS to `counterexample.html` | See `TOOLTIP_CSS` and `TOOLTIP_JS` strings in `apply_fixes.py` |

---

## About user account persistence

**Yes — user accounts are permanently stored** in the web portal's database
(SQLite locally, PostgreSQL on Render/production).

Accounts persist until:
- An administrator deletes the row from the `users` table directly.
- The database file/schema is dropped and recreated.

There is currently **no self-service account-deletion route** in the app.
If you want users to be able to delete their own accounts, add:

```python
@app.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    user = current_user
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Account deleted.", "info")
    return redirect(url_for("index"))
```

And add a confirmation button to `settings.html`.

---

## After applying

1. Restart Flask:  `python app.py` (or your launcher).
2. Visit `/dashboard` — KPIs and tool list should now populate from DB.
3. Visit `/active` — recent runs show both WEB and DSK sources.
4. Visit `/logs` — click **View** on any entry (including `DB_LOG_*`) to
   open the log modal with full content and LTL badges.
5. Visit `/counterexample/<id>` — hover over rules and trace steps for
   inline tooltips explaining the formal-verification terminology.
