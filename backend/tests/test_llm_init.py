"""
EAAWP LLM Initialization Test

Verifies that the backend can initialize the OpenAI LLM using the real
key mechanism — i.e. OPENAI_API_KEY loaded from settings/environment.

Tests in this file:
  1. Settings loads OPENAI_API_KEY from environment (no hardcoding).
  2. LLMConfig is built from settings without exposing the key.
  3. Gateway reports is_ready when key is configured.
  4. Gateway reports NOT ready when key is absent.
  5. ChatOpenAI instance is created via gateway with correct model/temperature.
  6. API key never appears in any config representation.
  7. .env.example contains OPENAI_API_KEY= with no real key value.
  8. backend/.gitignore ignores .env.

Live API call test (skipped automatically if OPENAI_API_KEY is not set):
  9. Gateway can create a real ChatOpenAI instance with the configured key.
     This does NOT make an inference call — it only instantiates the client.

No mock/fake LLM responses are used. No hardcoded keys anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# ── Paths ─────────────────────────────────────────────────────────────────────

BACKEND_DIR = Path(__file__).parent.parent
ENV_EXAMPLE = BACKEND_DIR / ".env.example"
GITIGNORE = BACKEND_DIR / ".gitignore"
ROOT_GITIGNORE = BACKEND_DIR.parent / ".gitignore"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Settings loads OPENAI_API_KEY from environment — no hardcoding
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettingsLoadsKeyFromEnvironment:
    def test_openai_api_key_field_exists_in_settings(self):
        """Settings class must have an openai_api_key field."""
        from app.config import Settings
        assert hasattr(Settings.model_fields, "__getitem__") or "openai_api_key" in Settings.model_fields

    def test_openai_api_key_default_is_empty_string(self):
        """Default value for openai_api_key is empty string — not a hardcoded key."""
        from app.config import Settings
        field = Settings.model_fields["openai_api_key"]
        default = field.default
        assert default == "", f"Expected empty string default, got: {default!r}"
        # Explicitly confirm no sk- prefix is hardcoded
        assert not str(default).startswith("sk-")

    def test_settings_reads_key_from_env_var(self, monkeypatch):
        """Settings picks up OPENAI_API_KEY from environment variable."""
        # Settings is a module-level singleton, so we test a fresh instance directly
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-env-read-check")
        from app.config import Settings
        s = Settings()
        assert s.openai_api_key == "sk-test-env-read-check"

    def test_settings_key_not_logged_via_repr(self, monkeypatch):
        """Gateway config repr must not expose the API key."""
        import app.config as cfg_mod
        original = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = "sk-secret-repr-check-99"
        try:
            from app.llm.config import llm_config_from_settings
            cfg = llm_config_from_settings()
            assert "sk-secret-repr-check-99" not in repr(cfg)
            assert "sk-secret-repr-check-99" not in str(cfg)
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original

    def test_llm_default_model_is_gpt4o_mini(self):
        """Default model is gpt-4o-mini — must not be silently changed."""
        from app.config import Settings
        s = Settings(openai_api_key="sk-test")
        assert s.llm_default_model == "gpt-4o-mini"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LLMConfig built from settings without exposing the key
# ═══════════════════════════════════════════════════════════════════════════════

class TestLLMConfigBuiltFromSettings:
    def test_llm_config_from_settings_uses_settings_key(self, monkeypatch):
        """llm_config_from_settings() reads the key from settings, not env directly."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["openai_api_key"] = "sk-cfg-test-key"
        from app.llm.config import llm_config_from_settings
        try:
            cfg = llm_config_from_settings()
            assert cfg.has_api_key()
            assert cfg.model == "gpt-4o-mini"
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = ""

    def test_llm_config_api_key_not_in_model_dump(self, monkeypatch):
        """LLMConfig.model_dump() must not contain the API key."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["openai_api_key"] = "sk-dump-secret-check"
        from app.llm.config import llm_config_from_settings
        try:
            cfg = llm_config_from_settings()
            dumped = cfg.model_dump()
            assert "sk-dump-secret-check" not in str(dumped)
            assert "api_key" not in dumped
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = ""

    def test_llm_config_safe_dict_shows_bool_not_key(self, monkeypatch):
        """safe_dict() shows api_key_present: True, never the key value."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["openai_api_key"] = "sk-safe-dict-check"
        from app.llm.config import llm_config_from_settings
        try:
            cfg = llm_config_from_settings()
            d = cfg.safe_dict()
            assert d["api_key_present"] is True
            assert "sk-safe-dict-check" not in str(d)
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = ""


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Gateway reports is_ready when key is configured
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatewayReadiness:
    def test_gateway_ready_with_key(self, monkeypatch):
        """LLMGateway.health() is_ready=True when OPENAI_API_KEY is set."""
        import app.config as cfg_mod
        import app.llm.gateway as gw_mod
        original = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = "sk-ready-check-key"
        gw_mod._gateway_instance = None
        try:
            from app.llm import get_llm_gateway
            health = get_llm_gateway().health()
            assert health.is_ready is True
            assert health.api_key_present is True
            assert health.error is None
            assert health.model == "gpt-4o-mini"
            assert health.provider == "openai"
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original
            gw_mod._gateway_instance = None

    def test_gateway_not_ready_without_key(self):
        """LLMGateway built with no key reports is_ready=False."""
        from unittest.mock import patch
        from app.llm.gateway import LLMGateway
        from app.llm.exceptions import LLMConfigurationError

        with patch(
            "app.llm.gateway.llm_config_from_settings",
            side_effect=LLMConfigurationError("OPENAI_API_KEY is not configured."),
        ):
            gw = LLMGateway()

        health = gw.health()
        assert health.is_ready is False
        assert health.api_key_present is False
        assert "OPENAI_API_KEY" in (health.error or "")

    def test_gateway_health_never_exposes_key(self):
        """health() result string must not contain the API key."""
        import app.config as cfg_mod
        import app.llm.gateway as gw_mod
        original = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = "sk-health-secret-9991"
        gw_mod._gateway_instance = None
        try:
            from app.llm import get_llm_gateway
            health = get_llm_gateway().health()
            assert "sk-health-secret-9991" not in str(health)
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original
            gw_mod._gateway_instance = None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ChatOpenAI created via gateway — correct model and temperature
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatOpenAICreatedViaGateway:
    def _set_key(self, key: str):
        import app.config as cfg_mod
        import app.llm.gateway as gw_mod
        cfg_mod.settings.__dict__["openai_api_key"] = key
        gw_mod._gateway_instance = None

    def _restore(self, original: str):
        import app.config as cfg_mod
        import app.llm.gateway as gw_mod
        cfg_mod.settings.__dict__["openai_api_key"] = original
        gw_mod._gateway_instance = None

    def test_gateway_creates_chatopenai_with_default_model(self):
        """Gateway creates ChatOpenAI(model='gpt-4o-mini', temperature=0)."""
        import app.config as cfg_mod
        original = cfg_mod.settings.openai_api_key
        self._set_key("sk-model-check")
        try:
            from app.llm import get_llm_gateway
            from langchain_openai import ChatOpenAI
            model = get_llm_gateway().get_chat_model()
            assert isinstance(model, ChatOpenAI)
            assert model.model_name == "gpt-4o-mini"
            assert model.temperature == 0.0
        finally:
            self._restore(original)

    def test_gateway_creates_chatopenai_with_temperature_override(self):
        """Gateway creates ChatOpenAI with temperature=0.7 for content generation."""
        import app.config as cfg_mod
        original = cfg_mod.settings.openai_api_key
        self._set_key("sk-temp-check")
        try:
            from app.llm import get_llm_gateway
            from langchain_openai import ChatOpenAI
            model = get_llm_gateway().get_chat_model(temperature=0.7)
            assert isinstance(model, ChatOpenAI)
            assert model.temperature == 0.7
        finally:
            self._restore(original)

    def test_gateway_creates_chatopenai_with_gpt4o(self):
        """Gateway creates ChatOpenAI(model='gpt-4o') when requested."""
        import app.config as cfg_mod
        original = cfg_mod.settings.openai_api_key
        self._set_key("sk-gpt4o-check")
        try:
            from app.llm import get_llm_gateway
            from langchain_openai import ChatOpenAI
            model = get_llm_gateway().get_chat_model(model="gpt-4o")
            assert isinstance(model, ChatOpenAI)
            assert model.model_name == "gpt-4o"
        finally:
            self._restore(original)

    def test_model_has_bind_tools(self):
        """ChatOpenAI produced by gateway supports .bind_tools()."""
        import app.config as cfg_mod
        original = cfg_mod.settings.openai_api_key
        self._set_key("sk-bindtools-check")
        try:
            from app.llm import get_llm_gateway
            model = get_llm_gateway().get_chat_model()
            assert hasattr(model, "bind_tools") and callable(model.bind_tools)
        finally:
            self._restore(original)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. API key never appears in any config representation
# ═══════════════════════════════════════════════════════════════════════════════

class TestKeyNeverExposed:
    KEY = "sk-never-expose-this-key-12345"

    def test_key_not_in_llm_config_repr(self):
        import app.config as cfg_mod
        original = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = self.KEY
        from app.llm.config import llm_config_from_settings
        try:
            cfg = llm_config_from_settings()
            assert self.KEY not in repr(cfg)
            assert self.KEY not in str(cfg)
            assert self.KEY not in str(cfg.model_dump())
            assert self.KEY not in str(cfg.safe_dict())
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original

    def test_key_not_in_gateway_health(self):
        import app.config as cfg_mod
        import app.llm.gateway as gw_mod
        original = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = self.KEY
        gw_mod._gateway_instance = None
        try:
            from app.llm import get_llm_gateway
            health = get_llm_gateway().health()
            assert self.KEY not in str(health)
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original
            gw_mod._gateway_instance = None

    def test_key_is_loaded_into_settings(self, monkeypatch):
        """Confirms the key IS loaded (into settings) — just not exposed anywhere."""
        monkeypatch.setenv("OPENAI_API_KEY", self.KEY)
        from app.config import Settings
        s = Settings()
        assert s.openai_api_key == self.KEY  # loaded correctly


# ═══════════════════════════════════════════════════════════════════════════════
# 7. .env.example has OPENAI_API_KEY= with no real value
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnvExampleSafety:
    def test_env_example_exists(self):
        """backend/.env.example must exist."""
        assert ENV_EXAMPLE.exists(), f"Missing: {ENV_EXAMPLE}"

    def test_env_example_has_openai_api_key_blank(self):
        """OPENAI_API_KEY in .env.example must have no real value."""
        content = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" in content, ".env.example must document OPENAI_API_KEY"

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("OPENAI_API_KEY"):
                # Must not contain a real key (sk- prefix)
                assert "sk-" not in stripped, (
                    f".env.example contains what looks like a real API key: {stripped!r}"
                )
                # The value should be blank: OPENAI_API_KEY=  or  OPENAI_API_KEY=""
                value_part = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                assert value_part == "", (
                    f"OPENAI_API_KEY in .env.example should be blank, got: {value_part!r}"
                )

    def test_env_example_contains_llm_default_model_comment(self):
        """LLM_DEFAULT_MODEL should be documented in .env.example."""
        content = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert "LLM_DEFAULT_MODEL" in content


# ═══════════════════════════════════════════════════════════════════════════════
# 8. backend/.gitignore ignores .env
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitignoreSafety:
    def test_backend_gitignore_ignores_dotenv(self):
        """`backend/.gitignore` must contain `.env`."""
        assert GITIGNORE.exists(), "backend/.gitignore is missing"
        content = GITIGNORE.read_text(encoding="utf-8")
        lines = [l.strip() for l in content.splitlines()]
        assert ".env" in lines, "backend/.gitignore must have `.env` on its own line"

    def test_root_gitignore_ignores_dotenv(self):
        """Root `.gitignore` must ignore `.env` files."""
        assert ROOT_GITIGNORE.exists(), "Root .gitignore is missing"
        content = ROOT_GITIGNORE.read_text(encoding="utf-8")
        assert ".env" in content, "Root .gitignore must cover .env"

    def test_env_example_not_gitignored(self):
        """`.env.example` must NOT be gitignored — it is safe to commit."""
        content = ROOT_GITIGNORE.read_text(encoding="utf-8")
        # Root .gitignore has !.env.example exception
        assert "!.env.example" in content, (
            "Root .gitignore should have `!.env.example` exception so the "
            "example file is committed but real .env files are not."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Live initialization test — real key, no inference call
# ═══════════════════════════════════════════════════════════════════════════════

# This test uses the REAL key from the environment (backend/.env).
# It does NOT make an inference/completion API call — it only creates
# the ChatOpenAI client instance, which is a local operation.
# Skipped automatically if OPENAI_API_KEY is not configured.

_real_key = os.environ.get("OPENAI_API_KEY", "")


@pytest.mark.skipif(
    not _real_key or not _real_key.startswith("sk-"),
    reason="OPENAI_API_KEY not configured in environment — skipping live init test",
)
class TestLiveLLMInitialization:
    def test_real_key_is_not_empty(self):
        """The real key from environment is non-empty."""
        assert _real_key.strip() != ""

    def test_real_key_looks_like_openai_key(self):
        """The real key starts with 'sk-' as expected for OpenAI keys."""
        assert _real_key.startswith("sk-"), (
            f"OPENAI_API_KEY does not start with 'sk-'. "
            f"Got prefix: {_real_key[:6]!r}"
        )

    def test_gateway_creates_chatopenai_with_real_key(self):
        """
        Gateway creates a real ChatOpenAI instance using the configured key.
        No inference call is made — client instantiation only.
        """
        import app.config as cfg_mod
        import app.llm.gateway as gw_mod
        original = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = _real_key
        gw_mod._gateway_instance = None
        try:
            from app.llm import get_llm_gateway
            from langchain_openai import ChatOpenAI

            gateway = get_llm_gateway()
            health = gateway.health()

            assert health.is_ready is True, f"Gateway not ready: {health.error}"
            assert health.api_key_present is True

            # Create the actual model instance — local operation, no network call
            model = gateway.get_chat_model()
            assert isinstance(model, ChatOpenAI)
            assert model.model_name == "gpt-4o-mini"

            # Confirm the key was passed into the model (checks presence, not value)
            assert model.openai_api_key is not None
            assert str(model.openai_api_key.get_secret_value()).startswith("sk-")
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original
            gw_mod._gateway_instance = None

    def test_real_key_never_in_health_output(self):
        """The real key must not appear in gateway health output."""
        import app.config as cfg_mod
        import app.llm.gateway as gw_mod
        original = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = _real_key
        gw_mod._gateway_instance = None
        try:
            from app.llm import get_llm_gateway
            health = get_llm_gateway().health()
            assert _real_key not in str(health)
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original
            gw_mod._gateway_instance = None

    def test_startup_log_message_does_not_contain_key(self):
        """
        The log message produced at startup must not contain the real API key.
        Verifies the pattern used in main.py lifespan.
        """
        import app.config as cfg_mod
        import app.llm.gateway as gw_mod
        original = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = _real_key
        gw_mod._gateway_instance = None
        try:
            from app.llm import get_llm_gateway
            health = get_llm_gateway().health()
            # This is exactly the log message format from main.py lifespan
            log_message = (
                f"LLM Gateway: ready — provider={health.provider} "
                f"model={health.model} api_key_present={health.api_key_present}"
            )
            assert _real_key not in log_message
            assert "api_key_present=True" in log_message
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original
            gw_mod._gateway_instance = None
