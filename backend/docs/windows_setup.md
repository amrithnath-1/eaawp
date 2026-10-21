# EAAWP on Windows: install, update, run, back up

For running EAAWP on **your own Windows PC** (development / pilot use). It is not a production deployment guide: do not expose these servers to the internet.
All commands are PowerShell. Replace `<PROJECT>` with the folder that contains `package.json` (for example `C:\Users\you\Desktop\eaawp`).

## 1. Install the prerequisites once
| Tool | Version | Check |
|---|---|---|
| Python | 3.11 or newer (developed on 3.13) | `python --version` |
| Node.js | 20.19+ or 22.12+ (the front end's build tool requires this) | `node --version` |
| Git | any recent | `git --version` |

Install Python from python.org (tick **Add python.exe to PATH**) and Node.js LTS from nodejs.org.

## 2. Get the code
```powershell
cd <parent folder>
git clone https://github.com/amrithnath-1/eaawp.git
cd eaawp          # this is <PROJECT>
```
The `master` branch is the current verified code.

## 3. Back end (first install)
```powershell
cd <PROJECT>\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env          # only if .env does not exist yet; never overwrite an existing .env
```
Now **open `backend\.env` in an editor** and set the two required values yourself (never paste them into a chat or commit them):
* `SECRET_KEY`: generate one with `.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"` and paste the output. The server refuses to start with an empty or placeholder key.
* `GEMINI_API_KEY`: your Google Gemini key from https://aistudio.google.com/app/apikey (needed for AI answers and document search; the rest of the app starts without it).

Create the database tables (a new database starts empty, and the server never migrates by itself):
```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current        # prints the revision followed by "(head)"
```
Start the back end:
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Check `http://127.0.0.1:8000/health`: it must show `"database_schema":"ok"`. `"out_of_date"` means the migration step above is still needed.
Leave this window open.

## 4. Front end (second PowerShell window)
```powershell
cd <PROJECT>
npm install
```
Create `<PROJECT>\.env` containing exactly:
```
VITE_USE_REAL_API=true
VITE_API_BASE_URL=http://localhost:8000
```
```powershell
npm run dev
```
Open **http://localhost:5173**. Use `localhost` (not `127.0.0.1`) unless you added that origin to `CORS_ORIGINS` in `backend\.env`.

## 5. First use
1. On the sign-in screen choose **New Company**, enter the company name and the first administrator. **Write down the company ID** shown afterwards; it is part of every sign-in.
2. Sign in, open **Library**, upload a document you are allowed to use, wait for it to finish indexing, then ask the **Cabin** about it.
3. Add colleagues in **Team** (invitation links; the link can be copied if email is not set up). Turn modules on or off in **Marketplace**.
4. Optional: set up the company's email connection in **Integrations**, then **Settings > Notifications** to authorize notification emails (off by default; each person must also opt in).

## 6. Updating an existing install (keeps your data)
Always **back up first**. Close both servers, then:
```powershell
cd <PROJECT>
git status                                   # your own changes must be committed or understood first; do not run "git reset --hard"
git pull --ff-only origin master             # refuses to run if it cannot fast-forward
cd backend
# 1) which database file is used? (credentials hidden)
.\.venv\Scripts\python.exe -c "from app.config import settings; print(settings.database_url.split('@')[-1])"
# 2) back up the SQLite file and uploaded documents (adjust the name if the line above shows another file)
Copy-Item .\eaawp.db ".\eaawp.db.bak-$(Get-Date -Format yyyyMMdd-HHmm)"
Copy-Item .\uploads ".\uploads.bak-$(Get-Date -Format yyyyMMdd-HHmm)" -Recurse
# 3) new dependencies, then migrate
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current        # must end with "(head)"
cd ..
npm install
```
Then start both servers as in sections 3 and 4. If a migration fails, stop, keep the backup, and do not edit the database by hand: copy the backup file back over `eaawp.db` and report the error text. Migrations here only add tables and columns.
**Never** copy `.env`, `eaawp.db` or `uploads` into Git or a chat: they hold your keys and company data.

## 7. Everyday use
* **Start**: two PowerShell windows (back end, then front end) as above. **Stop**: `Ctrl+C` in each window.
* **Back up**: copy `backend\eaawp.db`, `backend\uploads` and `backend\.env` to a safe place regularly (and before every update). The `.env` copy matters: `SECRET_KEY` (and `ENCRYPTION_KEY` if set) decrypts the saved integration credentials, and losing it means reconnecting them.
* **Reset one company's password / locked out**: sign in as another administrator and use **Team**; do not edit the database.

## 8. Troubleshooting
| Symptom | Cause and fix |
|---|---|
| "CORS error" or "Failed to fetch" in the browser | Usually the back end is down, or the database is behind the code (health shows `out_of_date`): run `alembic upgrade head`. Also check you opened the exact origin listed in `CORS_ORIGINS` (`.\.venv\Scripts\python.exe -c "from app.config import settings; print(settings.cors_origins_list)"`). |
| `running scripts is disabled on this system` | You tried `Activate.ps1`. Not needed: the commands above call `.\.venv\Scripts\python.exe` directly. |
| Back end exits at start with a SECRET_KEY message | Empty, short (under 32 characters) or placeholder key: set a real one in `backend\.env`. |
| `address already in use` (port 8000 or 5173) | Another copy is running. Close it, or find it with `netstat -ano \| findstr :8000` and stop that process in Task Manager. |
| AI answers say the model is not configured | `GEMINI_API_KEY` is missing in `backend\.env`; restart the back end after editing. |
| Sign-in says company not found | Enter the company ID shown at registration (not the company name). |
| Pages show no data after an update | Hard-refresh the browser (`Ctrl+F5`), then check `/health`. |

## 9. What is and is not verified
Verified by me in a Linux test environment: a brand-new database is reported `out_of_date` by `/health`, `alembic upgrade head` creates it, and `/health` then reports `ok`; the full test suite; browser checks of the screens. **Not verified on a real Windows machine by me:** the exact PowerShell commands above (they use standard Windows paths and `.venv\Scripts`), `npm install` on your Node version, and OneDrive-synced folders (OneDrive can lock `eaawp.db`; keep the project outside OneDrive or pause syncing while the back end runs). If any step prints an error, send me the error text (never your `.env`).
