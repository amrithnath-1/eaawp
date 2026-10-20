"""
EAAWP test configuration.

Isolates LLM gateway state between tests so that real API keys
or provider settings in the process environment and .env file
cannot contaminate tests that monkeypatch their own values.
"""
from __future__ import annotations
import pytest

_LLM_ENV_VARS = (
    "GEMINI_API_KEY",
    "LLM_DEFAULT_PROVIDER",
    "GEMINI_DEFAULT_MODEL",
)

# Settings fields that must be restored to safe defaults before each test.
# Tests that need specific values set them explicitly via settings.__dict__.
_SETTINGS_DEFAULTS = {
    "llm_default_provider": "openai",   # prevent Gemini from being auto-selected
    "gemini_api_key": "",               # prevent real key from leaking into OpenAI tests
}


@pytest.fixture(autouse=True)
def _isolate_llm_state(monkeypatch):
    """
    Before every test:
      - Clear Gemini env vars so monkeypatch.setenv is the sole authority.
      - Reset settings fields to safe defaults for test isolation.
      - Reset the LLM gateway singleton.
    After every test:
      - monkeypatch restores env vars automatically.
      - Restore settings fields.
      - Reset singleton.
    """
    import app.llm.gateway as gw_mod
    import app.config as cfg_mod

    # Clear env vars
    for var in _LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    # Snapshot & reset settings to safe defaults
    snapshot = {k: getattr(cfg_mod.settings, k) for k in _SETTINGS_DEFAULTS}
    for k, v in _SETTINGS_DEFAULTS.items():
        cfg_mod.settings.__dict__[k] = v

    gw_mod._gateway_instance = None
    yield
    gw_mod._gateway_instance = None

    # Restore settings snapshot
    for k, v in snapshot.items():
        cfg_mod.settings.__dict__[k] = v


# ── Shared two-tenant world for security tests ──────────────────────────────
import asyncio
import uuid



from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_SECRET = "security-test-secret-key-0123456789abcdef"
PASSWORD = "Correct-Horse-Battery-9"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_PASSWORD_HASH: str | None = None


def _password_hash() -> str:
    """bcrypt is deliberately slow; hash the shared test password once."""
    global _PASSWORD_HASH
    if _PASSWORD_HASH is None:
        from app.core.auth import hash_password

        _PASSWORD_HASH = hash_password(PASSWORD)
    return _PASSWORD_HASH


class World:
    """Two tenants with an admin + employee in A and an admin in B."""

    def __init__(self) -> None:
        self.client: TestClient | None = None
        self.tenant_a = f"tenant-a-{uuid.uuid4().hex[:8]}"
        self.tenant_b = f"tenant-b-{uuid.uuid4().hex[:8]}"
        self.users: dict[str, dict] = {}

    # -- tokens ---------------------------------------------------------------
    def token(self, who: str) -> str:
        from app.core.auth import create_access_token

        u = self.users[who]
        return create_access_token(u["id"], u["email"], u["tenant_id"], u["role"])

    def auth(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(who)}"}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    from app import config
    import importlib, pkgutil
    import app.db as _dbpkg
    for _m in pkgutil.iter_modules(_dbpkg.__path__):
        if _m.name != 'seed':
            importlib.import_module(f'app.db.{_m.name}')  # register every table
    from app.db.models import Base
    from app.db.session import get_db
    from app.main import app

    monkeypatch.setattr(config.settings, "secret_key", TEST_SECRET)
    monkeypatch.setattr(config.settings, "algorithm", "HS256")
    monkeypatch.setattr(config.settings, "access_token_expire_minutes", 60)
    monkeypatch.setattr(config.settings, "environment", "development")

    db_file = tmp_path / "security.db"
    # NullPool: every session opens its own connection on the *current* event
    # loop, so the same DB works from sync TestClient and async httpx tests.
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _create_schema():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    _run(_create_schema())

    w = World()

    async def _seed():
        from app.db.models import Company, User

        async with maker() as s:
            for tid, name in ((w.tenant_a, "Company A"), (w.tenant_b, "Company B")):
                s.add(Company(id=tid, name=name, industry="x", region="x", employees=1, is_active=True))
            await s.flush()
            spec = {
                "a_admin": (w.tenant_a, "Company Admin"),
                "a_employee": (w.tenant_a, "Employee"),
                "b_admin": (w.tenant_b, "Company Admin"),
                "b_employee": (w.tenant_b, "Employee"),
            }
            for key, (tid, role) in spec.items():
                uid = str(uuid.uuid4())
                email = f"{key}@example.test"
                s.add(User(id=uid, tenant_id=tid, email=email, name=key, role=role,
                           hashed_password=_password_hash(), status="Active", is_active=True))
                w.users[key] = {"id": uid, "email": email, "tenant_id": tid, "role": role}
            await s.commit()

    _run(_seed())

    async def _override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    # No ``with`` block: the lifespan (scheduler, seeding) must not run in tests.
    w.client = TestClient(app, raise_server_exceptions=False)
    w.maker = maker  # type: ignore[attr-defined]
    try:
        yield w
    finally:
        app.dependency_overrides.pop(get_db, None)
        _run(engine.dispose())


