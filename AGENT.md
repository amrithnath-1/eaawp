# EAAWP — Senior Engineer Brief

**Status as of October 2026 | For handoff / next developer**

This document tells you everything you need to know to take this project from its current state to a production-ready product. It is written from a position of having read the full codebase, not from assumptions.

---

## What this project is

EAAWP (Enterprise Agentic AI Workforce Platform) is a multi-tenant SaaS application that deploys AI "employees" inside a company. Each AI employee has a defined role, a set of permitted tools, and an approval governance layer. The first and only fully implemented role is the **Digital Marketing Manager (DMM)**.

A user logs in, lands in the **Cabin** (the chat interface), and asks their AI agent anything. The agent reasons using Google Gemini, calls real tools (campaign analytics, document search, email drafting, database queries), routes sensitive actions through a human approval flow, and logs everything in an audit trail.

---

## 1. How to run it locally

### Prerequisites
- Python 3.12+ with a virtual environment
- Node.js 20+
- A Gemini API key from https://aistudio.google.com/app/apikey

### Backend
```bash
cd kinetic-office-main/backend
cp .env.example .env          # then fill in GEMINI_API_KEY and SECRET_KEY
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Watch for:
```
LLM Gateway: ready — provider=google model=gemini-3.5-flash-lite api_key_present=True
Application startup complete.
```

### Frontend
```bash
cd kinetic-office-main
npm install
cp .env.example .env          # set VITE_USE_REAL_API=true and VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

Open http://localhost:5173 (or 5174 if 5173 is busy).

### First login
Use the onboarding flow at `/company` to create your first company and admin account. Or use the seed user:
- Email: `admin@demo.eaawp.io`
- Password: `demo1234`
- Company ID: `demo-company-001`

---

## 2. Architecture in one page

```
Browser (React + TanStack Router)
        │  JWT Bearer + X-Tenant-ID on every request
        ▼
FastAPI (port 8000)
  ├── Auth router          → JWT issue/refresh/revoke
  ├── Execution router     → POST /api/v1/agent/execute  ← main entry point
  │     ├── Blueprint override (server always wins — no client injection)
  │     ├── RAG retrieval  (Gemini embeddings → DocumentChunk table)
  │     ├── Dynamic tools  (per-tenant CapabilityGrant → live integrations)
  │     ├── Simple engine  (DynamicAgentEngine → Gemini → tool loop)
  │     └── Planner mode   (multi-step plan → governance → approval pause)
  ├── 35 other routers     → CRUD for every domain entity
  └── Monitoring scheduler → APScheduler evaluating MonitoringRule rows
        │
        ▼
SQLite (dev) / PostgreSQL (prod)    ← DATABASE_URL in .env
        │
        ▼
External providers
  ├── Google Gemini API          ← GEMINI_API_KEY
  ├── PostgreSQL / MySQL         ← encrypted credentials in DB
  ├── Google Search Console      ← OAuth2 tokens in DB
  ├── Google Analytics           ← OAuth2 tokens in DB
  ├── Facebook                   ← API key in DB
  ├── GitHub                     ← API key in DB
  ├── MCP servers                ← server_url + optional api_key in DB
  └── SMTP email                 ← encrypted credentials in DB
```

---

## 3. Key environment variables

All of these go in `backend/.env`. Never commit `.env`. Use `.env.example` as the template.

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | **Yes** | JWT signing — must be ≥32 random chars. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GEMINI_API_KEY` | **Yes** | All LLM inference and document embeddings |
| `DATABASE_URL` | No | Defaults to SQLite. Set PostgreSQL URL for production |
| `LLM_DEFAULT_PROVIDER` | No | Set to `google` to use Gemini as default |
| `GEMINI_DEFAULT_MODEL` | No | Defaults to `gemini-3.5-flash-lite` |
| `CORS_ORIGINS` | No | Comma-separated allowed origins, e.g. `http://localhost:5173,http://localhost:5174` |
| `OPENAI_API_KEY` | Optional | Only needed if you want GPT models or OpenAI embeddings. Not required for Gemini. |
| `ENVIRONMENT` | No | `development` or `production`. Production disables all dev shortcuts. |

Frontend `.env` (in `kinetic-office-main/`):

| Variable | Required | Purpose |
|---|---|---|
| `VITE_USE_REAL_API` | **Yes** | Set to `true` to connect to real backend |
| `VITE_API_BASE_URL` | No | Defaults to `http://localhost:8000` |

---

## 4. What is fully working

| Feature | Status |
|---|---|
| Auth (login, JWT, refresh, logout) | ✅ Complete |
| Company onboarding | ✅ Complete |
| Cabin chat with Gemini | ✅ Working (quota-limited on free tier) |
| Campaign analytics tools | ✅ Complete |
| Content generation tools | ✅ Complete |
| Funnel analysis tools | ✅ Complete |
| Strategy analysis tools | ✅ Complete |
| Knowledge base upload + retrieval | ✅ Complete (requires OPENAI_API_KEY for embeddings currently) |
| PostgreSQL / MySQL data connections | ✅ Complete |
| MCP server connections | ✅ Complete (with SSRF protection) |
| Google Search Console OAuth | ✅ Complete |
| Email drafting + governed sending | ✅ Complete |
| Approval governance pipeline | ✅ Complete |
| Monitoring rules + scheduler | ✅ Complete |
| Workflow engine | ✅ Complete |
| Audit trail | ✅ Complete |
| Multi-step planning | ✅ Working (synthesis improves with quota) |
| Security hardening (9 fixes) | ✅ Applied |

---

## 5. What is incomplete

These are the known gaps in priority order.

### P1 — Must fix before any real users

**1. `GET /api/v1/companies` has no authentication and no tenant filter**
- File: `backend/app/api/routers/companies.py`, line 14
- Any unauthenticated request returns ALL companies in the database
- Fix: add `current_user: User = Depends(get_current_user)` and filter by `Company.id == current_user.tenant_id` — or restrict to superadmin only

**2. `ExecutionPlan` fetched by ID without tenant check**
- File: `backend/app/api/routers/execution.py`, line 221
- `select(ExecutionPlan).where(ExecutionPlan.id == plan_id)` — no tenant_id filter
- A user who guesses a plan_id from another tenant can read it
- Fix: add `.where(ExecutionPlan.tenant_id == tenant_id)` to the query

**3. Knowledge base embeddings require OpenAI**
- File: `backend/app/services/vector_store.py` and `backend/app/services/document_processor.py`
- Document upload and retrieval both use `text-embedding-3-small` via OpenAI
- If `OPENAI_API_KEY` is not set, RAG silently returns no results
- Fix: migrate to `gemini-embedding-exp-03-07` or `text-embedding-004` via `langchain_google_genai.GoogleGenerativeAIEmbeddings`. The embedding dimension changes — all existing chunks must be re-indexed.

### P2 — Significant UX gaps

**4. Cabin approval buttons are UI stubs**
- File: `src/routes/cabin.tsx`, lines around `requiresApproval`
- The "Approve", "Request changes", "Open task" buttons only call `toast.success()`
- They do not call `useResumePlan()` or `useApproveAction()`
- Fix: wire the Approve button to `useResumePlan({ planId })` when `planStatus === "awaiting_approval"`, and to `useApproveAction({ auditId })` for action-level approvals

**5. Scheduled page — schedule editor is a toast stub**
- File: `src/routes/scheduled.tsx` (the "Schedule editor" button)
- Fix: build a simple modal that POSTs to `PATCH /api/v1/schedules/{id}`

**6. Voice input and file attach in Cabin are stubs**
- Files: `src/routes/cabin.tsx` — microphone and paperclip buttons call `toast()`
- These require separate speech-to-text and file storage services
- Fix for file attach: reuse the existing `useUploadDocument()` hook from the Library page, scoped to the current conversation

### P3 — Technical debt

**7. 13 identical `*Fetch` helper functions in `use-api.ts`**
- `intFetch`, `dataFetch`, `actionFetch`, `monFetch`, `emailFetch`, `campFetch`, `perfFetch`, `funnelFetch`, `stratFetch`, `contentFetch`, `notifFetch`, `chanFetch`, `intMgrFetch` — all do the same switch-on-method dispatch through `apiClient`
- Fix: replace all 13 with a single `apiFetch<T>(method, path, body?)` function. ~200 lines of dead code removed.

**8. `_tenant()` defined identically in 20+ backend routers**
- Every router has: `def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str: return x_tenant_id`
- This is the old pre-JWT pattern. Most of these routers have been moved to `get_current_user` / `get_current_tenant_id` but some still use the raw header
- Fix: delete the local `_tenant` definition in each router and import `get_current_tenant_id` from `app.core.auth`

**9. `src/lib/error-reporting.ts` is a TODO stub**
- The frontend has a `reportError()` function that only `console.error`s in dev
- No errors reach any external service
- Fix: add Sentry (free tier) — 4 lines: `npm install @sentry/react`, `Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN })` in `main.tsx`, replace the TODO comment in `error-reporting.ts` with `Sentry.captureException(error, { extra: details })`

**10. `README.md` describes the old prototype — not the real system**
- File: `kinetic-office-main/README.md`
- Fixed by the new README written alongside this document

**11. Vector store is in-memory numpy — not production-grade**
- File: `backend/app/services/vector_store.py`
- Loads ALL document chunks into Python memory for cosine similarity
- Fine for ≤ 10,000 chunks. Will OOM under real load.
- Fix for production: switch `DATABASE_URL` to PostgreSQL and add `pgvector` extension. The `vector_store.py` module is explicitly designed to be swapped.

**12. Only one AI role implemented**
- `DIGITAL_MARKETING_MANAGER` is the only active role. All others return HTTP 404 with "coming soon"
- Adding a new role requires: a new `RoleConfiguration` seed, tool scope definitions, and a role key entry in `IMPLEMENTED_ROLES` in `app/schemas/role_config.py`
- The core engine, planner, governance and approval system are all role-agnostic — no core code needs changing

---

## 6. Database

**Default (development):** SQLite file at `backend/eaawp.db`. Zero setup.

**Production:** Set `DATABASE_URL=postgresql+asyncpg://user:password@host:5432/eaawp` and run Alembic migrations:
```bash
cd backend
.venv/Scripts/alembic upgrade head
```

Migrations are in `backend/migrations/versions/`. There are 20 versioned migration files covering the full schema. Never edit the SQLite file directly.

**Seed data:** `backend/app/db/seed.py` inserts a demo company and admin user. It is idempotent (checks before inserting). It is labelled development-only and must never run in production automatically.

---

## 7. Testing

```bash
cd backend
.venv/Scripts/python -m pytest --tb=short -q
```

Expected: ~1306 passed, ~5 known pre-existing isolation failures in `test_event_loop_fix.py` (they pass when run in isolation — this is a test-ordering issue, not a bug in production code).

Run a specific suite:
```bash
.venv/Scripts/python -m pytest tests/test_llm_tenant_fixes.py tests/test_security_and_e2e.py -v
```

---

## 8. Security summary

The following security hardening has been applied (see commit history for details):

- JWT required on all authenticated endpoints — no X-Tenant-ID header bypass
- Server-side blueprint override — clients cannot inject tool permissions
- File upload path traversal protection (UUID filenames, resolve check)
- SSRF protection on MCP and PostgreSQL provider URLs
- Startup refuses to boot with placeholder `SECRET_KEY`
- Admin role enforced on approval and user-creation endpoints
- Reviewer identity always from JWT, never from request body
- Prompt injection guard on all user inputs to the agent

**Two remaining gaps listed in P1 above must be fixed before real users.**

---

## 9. What the next developer should do first

In order:

1. Fix the two P1 access control issues (30 minutes)
2. Migrate document embeddings from OpenAI to Gemini (1–2 days)
3. Wire the Cabin approval buttons (2–3 hours)
4. Consolidate the 13 `*Fetch` helpers into one (1 hour)
5. Add Sentry to the frontend (30 minutes)
6. Update `README.md` — done, see alongside this file
7. Switch to PostgreSQL + pgvector for production
8. Set up a git remote (GitHub/GitLab) and add CI

---

## 10. Credentials required (names only — never paste real values)

```
GEMINI_API_KEY        — from https://aistudio.google.com/app/apikey
SECRET_KEY            — generate with: python -c "import secrets; print(secrets.token_hex(32))"
DATABASE_URL          — PostgreSQL connection string for production
GOOGLE_CLIENT_ID      — from Google Cloud Console (for GSC + GA OAuth)
GOOGLE_CLIENT_SECRET  — from Google Cloud Console
VITE_SENTRY_DSN       — from sentry.io (optional but recommended)
```

---

*This document was written by auditing the live codebase. Last updated: October 2026.*
