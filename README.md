# EAAWP — Enterprise Agentic AI Workforce Platform

A multi-tenant platform that deploys AI "employees" inside a company. Each AI employee has a defined role, access to permitted tools, and a human approval layer for sensitive actions.

**Current state:** Full-stack — React frontend + FastAPI backend + SQLite/PostgreSQL + Google Gemini.

---

## What it does

You log in as a company admin. You chat with your AI agent in the **Cabin**. The agent can:

- Search your company's indexed documents (RAG)
- Query connected databases using natural language
- Analyse campaign performance, content, funnels, and marketing strategy
- Draft and send emails (with approval before sending)
- Create internal tasks
- Connect to Google Search Console, Google Analytics, PostgreSQL, MySQL, GitHub, Facebook, or any MCP server
- Propose multi-step plans, pause for human approval, and resume after sign-off
- Monitor KPIs on a schedule and fire autonomous plans when thresholds are crossed

Every action is logged in an audit trail. Every sensitive action goes through a governance layer before execution.

---

## Quick start

### 1. Backend

```bash
cd kinetic-office-main/backend
cp .env.example .env
# Edit .env — set GEMINI_API_KEY and SECRET_KEY at minimum
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt       # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Mac/Linux
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload
```

Backend is ready when you see:
```
LLM Gateway: ready — provider=google model=gemini-3.5-flash-lite
Application startup complete.
```

### 2. Frontend

```bash
cd kinetic-office-main
npm install
# Create .env in this folder:
# VITE_USE_REAL_API=true
# VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

Open http://localhost:5173

### 3. Create your account

Go to the `/company` route and fill in your company name and admin details. Or use the development seed account:
- **Email:** `admin@demo.eaawp.io`
- **Password:** `demo1234`
- **Company ID:** `demo-company-001`

---

## Required environment variables

Copy `backend/.env.example` to `backend/.env` and fill in:

```
# Required
GEMINI_API_KEY=your-key-here          # https://aistudio.google.com/app/apikey
SECRET_KEY=generate-a-32-char-random-string

# Optional — defaults shown
DATABASE_URL=sqlite+aiosqlite:///./eaawp.db
LLM_DEFAULT_PROVIDER=google
GEMINI_DEFAULT_MODEL=gemini-3.5-flash-lite
CORS_ORIGINS=http://localhost:5173,http://localhost:5174
```

Generate a SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## How data flows

```
User types in Cabin
        ↓
POST /api/v1/agent/execute
        ↓
Server loads RoleConfiguration from DB
(overrides any tool permissions the client sent — client cannot self-escalate)
        ↓
If documents indexed → retrieve relevant chunks (RAG)
If DB integration connected → build data context
If CapabilityGrants exist → attach live integration tools
        ↓
Does the request need a multi-step plan?
  ├── No  → DynamicAgentEngine: one LLM call + tool execution loop
  └── Yes → Planner: LLM generates steps → execute → pause for approval if needed
        ↓
Response returned to frontend
Plan status + step summaries shown in Cabin
        ↓
If action needs approval → ApprovalRequest created
Admin approves in /approvals → action executes → audit record written
```

---

## Project structure

```
kinetic-office-main/
├── src/                          # React frontend
│   ├── routes/                   # One file per page (cabin, integrations, etc.)
│   ├── hooks/use-api.ts          # All API calls live here
│   ├── lib/api-client.ts         # JWT-aware HTTP client
│   └── state/session.tsx         # Auth state + localStorage
│
└── backend/
    ├── app/
    │   ├── main.py               # FastAPI app + all router registrations
    │   ├── config.py             # All settings (read from .env)
    │   ├── core/
    │   │   ├── auth.py           # JWT, bcrypt, tenant isolation
    │   │   └── engine.py         # DynamicAgentEngine — the LLM execution loop
    │   ├── api/routers/          # 35 routers, one per domain
    │   ├── services/
    │   │   ├── planner.py        # Multi-step plan generation + execution
    │   │   ├── vector_store.py   # Document embedding + cosine retrieval
    │   │   ├── action_governance.py  # Approval pipeline
    │   │   └── monitoring_engine.py  # Autonomous rule evaluation
    │   ├── tools/registry.py     # All 30+ LangChain @tool functions
    │   ├── integrations/         # PostgreSQL, GSC, GA, Facebook, GitHub, MCP, email
    │   ├── llm/                  # Gateway, config, Gemini + OpenAI providers
    │   └── db/
    │       ├── models.py         # All SQLAlchemy ORM models
    │       └── seed.py           # Development seed data (never runs in production)
    ├── migrations/               # Alembic migration files
    ├── tests/                    # ~1300 tests
    └── .env.example              # Copy this to .env
```

---

## Running tests

```bash
cd backend
.venv/Scripts/python -m pytest --tb=short -q
```

Expected: ~1306 passed.

---

## Known limitations

- **Free-tier Gemini quota:** 20 requests/day per model. Upgrade your API key or switch model if you hit the limit.
- **Document embeddings currently require OpenAI.** If `OPENAI_API_KEY` is not set, document upload works but search returns nothing. Migration to Gemini embeddings is in progress.
- **Only the Digital Marketing Manager role is active.** Other roles (Sales, Finance, HR, etc.) show "Coming Soon".
- **Cabin approval buttons** are wired for plan-level approval but not yet for individual action-level approval in the same view.
- **Vector store** loads all document chunks into memory. Fine for development; switch to PostgreSQL + pgvector for production loads.

---

## For the next developer

See **AGENT.md** for a complete handoff brief: what works, what is incomplete, the exact file and line for each known issue, and what to do in priority order.

---

## Licence

Academic / Final Year Project — not for commercial distribution without review.
