# EAAWP

**Enterprise Agentic AI Workforce Platform**

## Overview

EAAWP is an enterprise platform designed around continuously operating, role-specific Agentic AI employees. A company deploys one primary AI employee (for example a Data Intelligence Agent) that monitors permitted organisational information, performs authorised tasks, coordinates workflows across departments, communicates with enterprise systems, and surfaces proactive insights to the people who need them — with a full audit trail and human approval gates for sensitive actions.

## Current Prototype

The current implementation is a **frontend prototype** with simulated data. It demonstrates:

- **Cabin** — the primary AI employee workspace
- **AI prompting** — prompt-first interaction with suggested actions
- **AI activity** — chronological operational activity stream
- **Tasks** — active task tracking with progress, status and approvals
- **Proactive insights** — unprompted AI discoveries
- **AI environment visualisation** — floating organic agent/network layer
- **Meeting Room** — expanded department network visualisation
- **Letter Box** — user ↔ AI communication and document uploads
- **Scheduling** — recurring agent tasks
- **Company knowledge library** — indexed documents and sources
- **AI customisation** — capabilities, tools, permissions, autonomy levels
- **Role management**, **Audit logs**, and **Settings** (dark/light mode)

Authentication and all data are simulated in the browser; no backend services are connected yet.

## Future Architecture

Planned integrations (not yet implemented):

- LLM providers
- Agent orchestrator
- RAG pipeline
- Vector database
- Long-term agent memory
- Enterprise databases
- External APIs
- MCP / tool calling
- Workflow automation
- Authentication and authorisation
- Audit and monitoring

## Development

```sh
npm install
npm run dev
```

Copy `.env.example` to `.env` and fill in local values. Never commit real secrets.

## Tech Stack

TanStack Router · React 19 · TypeScript · Tailwind CSS v4 · Vite 8

## Project Structure

```
src/
  components/
    eaawp/     # Platform-specific UI components
    ui/        # shadcn/ui base components
  hooks/       # Custom React hooks
  lib/         # Utilities and helpers
  routes/      # File-based routes (TanStack Router)
  services/    # Mock data and service layer
  state/       # Global state (session, theme, agent status)
```
