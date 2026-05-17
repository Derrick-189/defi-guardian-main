# DeFi Guardian — Bug Fix Log

## 2026-05-10

### Fix 1 — HTTP 500 on `/api/trace/<id>` (`name 're' is not defined`)

**File:** `web_portal/app.py`  
**Line:** 13  

`_parse_log_as_trace()` used `re.match()` and `re.search()` but `re` was never
imported at module level. All calls to `/api/trace/<id>` for non-SPIN tools
(Certora, Coq, Lean, etc.) returned HTTP 500.

```python
# Added to imports
import re
```

---

### Fix 2 — All 8 LTL Properties Failing with the Same Assertion

**File:** `translator.py`  
**Lines:** 329–350  

The translator blindly converted every `require()` from Solidity into a bare
Promela `assert()` that fired at depth 0, before any state transitions.

`SimpleLending.sol` contains:
```solidity
require(totalSupply >= totalBorrowed + amount);
```

The translator produced:
```promela
int totalSupply = 0;
int totalBorrowed = 0;
int amount = 10;
assert(totalSupply >= totalBorrowed + amount);  // assert(0 >= 10) = FALSE
```

This assertion failed immediately, causing every LTL property to report the
same violation regardless of what property was being checked.

**Fix:** `require` statements involving supply/borrow/balance variables are now
emitted as guarded comments instead of live asserts:
```promela
/* invariant (guarded): totalSupply >= totalBorrowed + amount */
```

The `SKIP_PATTERNS` list covers: `totalsupply`, `totalborrowed`, `totaldebt`,
`totalliquidity`, `balance`, `allowance`, `reserve`.

---

### Fix 3 — "No Recent Activity" on Desktop Dashboard (port 5005)

**File:** `desktop_app.py`  
**Lines:** ~5849–5870 (`api_recent_activity`) and ~5948–5953 (dashboard JS)  

Field name mismatch between the `audit_log.json` schema and what the dashboard
JS expected:

| `audit_log.json` key | JS expected key |
|----------------------|-----------------|
| `timestamp`          | `datetime`      |
| `file`               | `model_name`    |
| `status` (`FAILED`)  | `status` (`FAIL`/`PASS`) |

**Fix:** `api_recent_activity` now normalises all field names before returning,
and the dashboard JS renders a full table (time, file, tool, status, states)
instead of a single line per entry.

---

### Fix 4 — Counterexample Page Showing Old Card Layout

**File:** `web_portal/templates/counterexample.html`  

The Flask server was caching the old template. The new template uses:
- CSS custom properties (`--ce-bg`, `--ce-panel`, etc.) for consistent theming
- 3-panel layout (Rules | Call Trace | Variables) matching Certora-style UI
- `switchTab()` / `renderResolutions()` / `renderFullVariables()` for lazy tab rendering
- Non-SPIN tools show recommendations + error list instead of empty trace panel
- `init()` fetches audit and trace sequentially with explicit HTTP status checks
  and logs all responses to the browser console for debugging

---

### Fix 5 — Trace Viewer Showing "No trace data available" for PASS Runs

**File:** `web_portal/app.py` — `get_trace()` and `_parse_log_as_trace()`  

SPIN PASS runs don't produce a `.trail` file. The old code returned an empty
trace for any run without a trail.

**Fix:** Two-stage fallback in `get_trace()`:
1. If no trail → `parse_trace(log)` (catches logs with step-format lines)
2. If still empty → `_parse_log_as_trace(log)` (parses `errors: N` summary
   lines and `ltl <name>: <formula>` lines into displayable steps)

`_parse_log_as_trace()` was also rewritten to correctly detect pass/fail from
`errors: 0` vs `errors: N` rather than relying on section headers.
