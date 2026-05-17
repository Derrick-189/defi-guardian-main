#!/usr/bin/env python3
"""Migration: add trace_data column to audit_history if missing."""
import sqlite3
import os

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'defi_guardian.db')

def has_column(conn, table, column):
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return column in cols

def main():
    if not os.path.exists(DB):
        print('DB not found:', DB)
        return
    conn = sqlite3.connect(DB)
    try:
        if has_column(conn, 'audit_history', 'trace_data'):
            print('Column trace_data already exists')
            return
        conn.execute('ALTER TABLE audit_history ADD COLUMN trace_data TEXT')
        conn.commit()
        print('Added trace_data column to audit_history')
    finally:
        conn.close()

if __name__ == '__main__':
    main()
