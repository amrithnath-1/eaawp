"""
EAAWP FastAPI Application Entry Point

Run locally:
    cd backend
    .venv\\Scripts\\uvicorn app.main:app --reload --port 8000

Environment variables (set in backend/.env):
    DATABASE_URL       — SQLAlchemy async URL (default: SQLite)
    OPENAI_API_KEY     — OpenAI API key
    SECRET_KEY         — JWT signing secret
    CORS_ORIGINS       — comma-separated allowed origins
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routers.execution import router as execution_router
from app.api.routers.companies import router as companies_router
from app.api.routers.users import router as users_router
from app.api.routers.llm_models import router as llm_models_router
from app.api.routers.ai_employees import router as ai_employees_router
from app.api.routers.agent_config import router as agent_config_router
from app.api.routers.role_config import router as role_config_router
from app.api.routers.config_interpreter import router as config_interpreter_router
from app.api.routers.knowledge import router as knowledge_router
from app.api.routers.integrations import router as integrations_router
from app.api.routers.data_access import router as data_access_router
from app.api.routers.actions import router as actions_router
from app.api.routers.planning import router as planning_router
from app.api.routers.tasks import router as tasks_router
from app.api.routers.activity import router as activity_router
from app.api.routers.insights import router as insights_router
from app.api.routers.schedules import router as schedules_router
from app.api.routers.approvals import router as approvals_router
from app.api.routers.audit import router as audit_router
from app.api.routers.monitoring import router as monitoring_router
from app.api.routers.email_integration import router as email_integration_router
from app.api.routers.email_drafts import router as email_drafts_router
from app.api.routers.campaigns import router as campaigns_router
from app.api.routers.performance import router as performance_router
from app.api.routers.funnel import router as funnel_router
from app.api.routers.strategy import router as strategy_router
from app.api.routers.content import router as content_router
from app.api.routers.memory import router as memory_router
from app.api.routers.notifications import router as notifications_router
from app.api.routers.channels import router as channels_router
from app.api.routers.reporting import router as reporting_router
from app.api.routers.onboarding import router as onboarding_router
from app.api.routers.llm_gateway import router as llm_gateway_router
from app.api.routers.integration_manager import router as integration_manager_router
from app.api.routers.oauth_router import router as oauth_router  # Phase 4 GSC OAuth
from app.api.routers.auth import router as auth_router  # Phase A — JWT auth
from app.api.routers.nl_integration import router as nl_integration_router  # Phase B — NL integration
from app.api.routers.employee_builder import router as employee_builder_router  # Phase H — employee builder
from app.api.routers.workflow import router as workflow_router  # Phase I — workflow engine
from app.api.routers.admin_customization import router as admin_customization_router  # Admin AI Customize
from app.api.routers.admin_config import router as admin_config_router  # Admin Config Engine
from app.middleware.observability import ObservabilityMiddleware  # Phase N

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan (startup + shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Start and stop the monitoring scheduler alongside the application."""
    from app.services.monitoring_scheduler import start_scheduler, stop_scheduler

    # ── Reject known-placeholder signing secret ───────────────────────────────
    # If SECRET_KEY still holds the repository default value the server cannot
    # safely sign JWTs — existing tokens cannot be trusted.  Refuse to start so
    # the operator is forced to set a real secret before going live.
    _PLACEHOLDER_SECRETS = {
        "dev-insecure-key-replace-in-production",
        "changeme",
        "secret",
        "replace-me",
        "your-secret-key",
    }
    if settings.secret_key in _PLACEHOLDER_SECRETS or len(settings.secret_key) < 32:
        raise RuntimeError(
            "SERVER STARTUP REFUSED: SECRET_KEY is a known placeholder or too short "
            "(minimum 32 characters).  Set a strong, unique SECRET_KEY in backend/.env "
            "before starting the server.  All previously issued JWTs signed with a "
            "placeholder key are invalid and must be re-issued after rotation."
        )

    logger.info("EAAWP backend starting — environment: %s", settings.environment)
    logger.info("Database: %s", settings.database_url.split("@")[-1])  # hide credentials

    # ── LLM configuration check ───────────────────────────────────────────────
    # Reports whether the API key is present without revealing it.
    # Does NOT make a live API call — safe to run at every startup.
    from app.llm import get_llm_gateway
    _llm_health = get_llm_gateway().health()
    if _llm_health.is_ready:
        logger.info(
            "LLM Gateway: ready — provider=%s model=%s api_key_present=%s",
            _llm_health.provider,
            _llm_health.model,
            _llm_health.api_key_present,
        )
    else:
        logger.warning(
            "LLM Gateway: NOT ready — provider=%s api_key_present=%s error=%s",
            _llm_health.provider,
            _llm_health.api_key_present,
            _llm_health.error,
        )
    # ─────────────────────────────────────────────────────────────────────────

    await start_scheduler()
    yield
    logger.info("EAAWP backend shutting down")
    await stop_scheduler()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    description="Enterprise Agentic AI Workforce Platform — Backend API",
    version=settings.app_version,
    # Interactive API docs expose the full route map; keep them off in production.
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None if settings.environment == "production" else "/redoc",
    openapi_url=None if settings.environment == "production" else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)  # Phase N — structured access logging

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(execution_router)
app.include_router(companies_router)
app.include_router(users_router)
app.include_router(llm_models_router)
app.include_router(ai_employees_router)
app.include_router(agent_config_router)
app.include_router(role_config_router)
app.include_router(config_interpreter_router)
app.include_router(knowledge_router)
app.include_router(integrations_router)
app.include_router(data_access_router)
app.include_router(actions_router)
app.include_router(planning_router)
app.include_router(tasks_router)
app.include_router(activity_router)
app.include_router(insights_router)
app.include_router(schedules_router)
app.include_router(approvals_router)
app.include_router(audit_router)
app.include_router(monitoring_router)
app.include_router(email_integration_router)
app.include_router(email_drafts_router)
app.include_router(campaigns_router)
app.include_router(performance_router)
app.include_router(funnel_router)
app.include_router(strategy_router)
app.include_router(content_router)
app.include_router(memory_router)
app.include_router(notifications_router)
app.include_router(channels_router)
app.include_router(reporting_router)
app.include_router(onboarding_router)
app.include_router(llm_gateway_router)
app.include_router(integration_manager_router)
app.include_router(oauth_router, prefix="/api/v1")  # Phase 4 — /api/v1/oauth/google/*
app.include_router(auth_router)  # Phase A — /api/v1/auth/*
app.include_router(nl_integration_router)  # Phase B — /api/v1/nl-integration/*
app.include_router(employee_builder_router)  # Phase H — /api/v1/employees/*
app.include_router(workflow_router)  # Phase I — /api/v1/workflows/*
app.include_router(admin_customization_router)  # Admin AI Customize — /api/v1/admin/customize/*
app.include_router(admin_config_router)  # Admin Config Engine — /api/v1/admin/provider-config/*


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}
