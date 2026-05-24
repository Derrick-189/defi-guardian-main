# TODO
- [ ] Update web_portal/api_v1.py on Render to add `GET /api/v1/audit-log/raw` that returns `generated/reports/audit_log.json`.
- [ ] Update web_portal/api_v1.py on local to add `POST /api/v1/sync-audit-remote` that downloads remote audit log JSON using `RENDER_BASE_URL` and calls a modified `sync_audit_log`.
- [ ] Update web_portal/audit_db.py to allow syncing from an in-memory audit log payload (optional param) instead of only reading from disk.
- [ ] Add minimal retry/error logging so failures are visible.
- [ ] Test: run local server, call sync endpoint, verify `Active Run` shows correct tool progress and `Recent Runs` updates.

