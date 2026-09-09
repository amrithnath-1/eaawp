"""
EAAWP FastAPI Application Entry Point

Run locally:
    uvicorn app.main:app --reload --port 8000

Environment variables required (set in backend/.env):
    OPENAI_API_KEY      — OpenAI API key for LLM calls
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.execution import router as execution_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── CORS origins ──────────────────────────────────────────────────────────────
# In development the Vite frontend runs on localhost:5173.
# In production replace with the real frontend origin.
_CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="EAAWP API",
    description="Enterprise Agentic AI Workforce Platform — Backend API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(execution_router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
