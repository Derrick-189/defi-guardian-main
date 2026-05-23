#!/usr/bin/env python3
"""Backfill trace_data for existing audit_history rows where possible."""
import sqlite3
import os
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'web_portal' / 'defi_guardian.db'
import sys
sys.path.insert(0, str(ROOT))

def main():
    if not DB.exists():
        print('DB not found:', DB)
        return
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute('SELECT id, tool_used, verification_output, report_path FROM audit_history').fetchall()
    from web_portal.trace_parsers import get_parser
    updated = 0
    for r in rows:
        aid = r['id']
        try:
            # Skip if trace_data already present
            existing = cur.execute('SELECT trace_data FROM audit_history WHERE id=?', (aid,)).fetchone()
            if existing and existing[0]:
                continue
        except Exception:
            # table might not have column yet
            print('trace_data column missing; run migration first')
            break

        tool = r['tool_used'] or ''
        parser = get_parser(tool)
        if not parser:
            continue
        log = r['verification_output'] or ''
        report = r['report_path'] or ''
        parsed = parser.parse_trace(log, report) if parser else None
        if parsed:
            payload = json.dumps(parsed.to_dict())
            cur.execute('UPDATE audit_history SET trace_data=? WHERE id=?', (payload, aid))
            updated += 1
            print('Updated', aid)
    conn.commit()
    conn.close()
    print('Done. Updated', updated)

if __name__ == '__main__':
    main()
