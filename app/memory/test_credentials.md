# DeFi Guardian — Test Credentials

## Demo Account
- **Username:** `demo`
- **Password:** `demo1234`
- **Email:** `demo@defiguardian.local`
- **Role:** user

## Admin Account (create manually)
```bash
python3 -c "
import sys; sys.path.insert(0, 'web_portal')
from audit_db import get_db, DB_PATH
from werkzeug.security import generate_password_hash
conn = get_db()
conn.execute(
    'INSERT OR IGNORE INTO users (username,email,password_hash,role) VALUES (?,?,?,?)',
    ('admin', 'admin@defiguardian.local', generate_password_hash('admin1234'), 'admin')
)
conn.commit(); conn.close()
print('Admin created')
"
```

## Portal URL
- http://localhost:5000

## API Endpoints
- GET  /api/state/current       — Latest verification state
- GET  /api/tools/status        — All 8 tool statuses
- GET  /api/ltl-properties      — LTL properties from last run
- GET  /api/counterexample/latest — Latest counterexample data
- POST /api/run                 — Trigger a verification run
- POST /api/generate-spec       — LLM spec generation
- POST /api/events/emit         — Desktop app event bridge
