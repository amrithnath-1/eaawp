# Running EAAWP locally on Windows (PowerShell)

> **Superseded for setup and updates by [windows_setup.md](windows_setup.md).** This note is kept as the history of one CORS / out-of-date-database incident; the migration revision ids below are historical (run `alembic upgrade head` and expect `(head)`).

Project folder: `C:\Users\mt602\OneDrive\Documents\Desktop\FINAL YEAR PROJECT\kinetic-office-main (1)\kinetic-office-main`

## If the app shows "CORS error", "Failed to fetch" or a 500 on `/api/v1/agent/pending-tasks`
Cause (reproduced): the local database is **behind the code**. A newer table (`pending_tasks`) and an
OAuth column do not exist yet, so the request crashes; a crashed response has no CORS header, so the
browser reports CORS instead of the real error. CORS itself is configured correctly.

### 1. Back up, then migrate (additive migrations only; nothing is dropped)
```powershell
cd "C:\Users\mt602\OneDrive\Documents\Desktop\FINAL YEAR PROJECT\kinetic-office-main (1)\kinetic-office-main\backend"
# which database does the backend really use? (credentials are hidden)
.\.venv\Scripts\python.exe -c "from app.config import settings; print(settings.database_url.split('@')[-1])"
# back up the SQLite file (skip if the line above is not a sqlite path)
Copy-Item .\eaawp.db ".\eaawp.db.bak-$(Get-Date -Format yyyyMMdd-HHmm)"
.\.venv\Scripts\python.exe -m alembic current          # expect: u8v2w37x9y15
.\.venv\Scripts\python.exe -m alembic upgrade head     # applies v9w3x48y0z16 and w0x4y59z1a17
.\.venv\Scripts\python.exe -m alembic current          # expect: w0x4y59z1a17 (head)
```
This exact path (`u8v2w37x9y15` -> head) was rehearsed on a copy containing a user: both
migrations applied, the user could still log in, and `pending-tasks` returned 200.
If `alembic current` prints something else, stop and tell me what it printed.

### 2. Restart both servers (two PowerShell windows)
```powershell
# window 1 - backend
cd "...\kinetic-office-main\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# window 2 - frontend
cd "...\kinetic-office-main"
npm run dev
```
Open `http://localhost:5173`, sign in again if asked.

### 3. Check the allowed origin without printing any secret
```powershell
cd "...\kinetic-office-main\backend"
.\.venv\Scripts\python.exe -c "from app.config import settings; print(settings.cors_origins_list)"
```
`http://localhost:5173` must be in the list. If you open the app as `http://127.0.0.1:5173`,
that exact origin must be listed too. Add origins via `CORS_ORIGINS` in `backend\.env`
(comma-separated, explicit origins only; `*` is refused in production).

### 4. Health check
`http://127.0.0.1:8000/health` should show `"database_schema":"ok"`. `"out_of_date"` means step 1 is
still needed; the backend log also prints the exact command at startup.

## What the code now does
* A database behind the code returns **503** `schema_out_of_date` with the fix command, and the
  response is readable from the allowed browser origin.
* Any other server error returns JSON `{detail, code, request_id}` (no traceback, SQL or
  parameters) with CORS headers for **listed origins only**. Authentication is unchanged.
* The server never migrates automatically.
