# EAAWP — Enterprise Agentic AI Workforce Platform

A multi-tenant platform that deploys AI "employees" inside a company. Each AI employee has a defined role, access to permitted tools, and a human approval layer for sensitive actions.

**Current state:** Full-stack development application — React frontend + FastAPI backend + SQLite/PostgreSQL + Google Gemini. It is not yet a production-ready multi-company service; see the limitations below.

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

> On Windows, follow the step-by-step guide in [`backend/docs/windows_setup.md`](backend/docs/windows_setup.md) (install, update with backup, troubleshooting).

### 1. Configure and start the backend

```bash
cd kinetic-office-main/backend
# Create backend/.env from backend/.env.example if it does not already exist.
# Set GEMINI_API_KEY to a Google Gemini API key (not an OAuth access token).
# Set SECRET_KEY to a unique random value. Never share either value.
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

### 2. Start the frontend

```bash
cd kinetic-office-main
npm install
# In the project root, create or check .env:
# VITE_USE_REAL_API=true
# VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

Open http://localhost:5173

### 3. Register a fresh company

On the sign-in screen, choose **New Company**. Enter the company name and the first administrator's details. Keep the company ID shown after registration; the administrator can then sign in and use the app.

Do not use a demo account for a real company. A new account starts without that company's policies, records, or connected services.

### 4. Add company knowledge and verify an answer

Sign in as the new administrator. Open **Library** and upload a policy or other document that the company is allowed to use for this pilot. Wait for indexing to finish, then ask the Cabin a question whose answer is plainly stated in that document. Check that the response reflects the document. If nothing has been uploaded or connected, the app has no company-specific data to answer from.

Use approved test material first. Do not upload sensitive or regulated information until the company has reviewed its hosting, access, retention, and AI-provider requirements.

### 5. Connect a supported service (optional)

Open **Integrations** and use a provider's setup form. The available providers and authorization steps depend on the integration. Google Analytics and Search Console require Google OAuth configuration by the service operator. GitHub requires a scoped personal access token. Never paste credentials into Cabin chat. A private physical server must be reachable over a customer-approved network connection; entering a server address alone cannot make a cloud-hosted EAAWP reach a private network.

---

## Required environment variables

Copy `backend/.env.example` to `backend/.env` and fill in:

```
# Required
GEMINI_API_KEY=your-key-here          # https://aistudio.google.com/app/apikey
SECRET_KEY=<paste output of the command below>   # required; placeholders are refused at startup

# Optional — defaults shown
DATABASE_URL=sqlite+aiosqlite:///./eaawp.db
LLM_DEFAULT_PROVIDER=google
GEMINI_DEFAULT_MODEL=gemini-3.5-flash-lite
CORS_ORIGINS=http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174
```

Generate a SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

The server refuses to start while `SECRET_KEY` is empty, shorter than 32 characters or contains placeholder text
(`changeme`, `replace`, ...). Production additionally requires explicit `CORS_ORIGINS` (frontend URL first) and
serves no API docs. Every authenticated endpoint needs a Bearer JWT in every environment; the `X-Tenant-ID`
header is ignored. See `backend/.env.example` for all settings (`ENCRYPTION_KEY`, rate limits and registration
controls, `TRUSTED_PROXY_COUNT`, `JWT_ISSUER`, `JWT_AUDIENCE`) and `backend/docs/security_phase2.md` for the security model.

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

## Before a company pilot or production deployment

- The current app supports a limited set of active role and integration workflows. Verify each needed provider and permission path before relying on it; Ahrefs is not currently available.
- Staff invitations and a complete in-app role/permission editor still need implementation. Do not assume every department role is ready for company-wide use.
- The current vector search implementation is suitable for development and small pilots, not large production document collections. A production deployment needs a scalable vector database, backups, monitoring, and a reviewed data-retention policy.
- Google OAuth integrations require valid OAuth client configuration. Gemini chat and embeddings require a valid Gemini API key; an OAuth access token is not interchangeable with that key.
- A cloud deployment cannot directly reach an isolated on-premises server without a secure network path or customer-side connector.
- Before production, configure HTTPS, managed secrets, a production database, backups, access recovery, audit retention, rate limits, and incident monitoring. Review applicable company privacy and security requirements.
- This repository's local development setup is not a hosted service. The operator must deploy and maintain the backend, database, and frontend for company users.

---

## For the next developer

See **AGENT.md** for a complete handoff brief: what works, what is incomplete, the exact file and line for each known issue, and what to do in priority order.

---

## Licence

Academic / Final Year Project — not for commercial distribution without review.
