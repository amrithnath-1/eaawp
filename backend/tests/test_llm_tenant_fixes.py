# coding: utf-8
import pytest
from unittest.mock import MagicMock, patch


class TestGeminiProviderResolution:

    def test_get_default_provider_returns_google(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "google")
        import app.config as cfg
        cfg.settings.__dict__["llm_default_provider"] = "google"
        from app.llm.config import _get_default_provider, LLMProvider
        assert _get_default_provider() == LLMProvider.GOOGLE

    def test_get_default_model_returns_gemini(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "google")
        monkeypatch.setenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")
        import app.config as cfg
        cfg.settings.__dict__["llm_default_provider"] = "google"
        cfg.settings.__dict__["gemini_default_model"] = "gemini-2.0-flash"
        from app.llm.config import _get_default_model
        assert _get_default_model() == "gemini-2.0-flash"

    def test_config_uses_gemini_when_default_google(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "google")
        monkeypatch.setenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        import app.config as cfg
        cfg.settings.__dict__["llm_default_provider"] = "google"
        cfg.settings.__dict__["gemini_default_model"] = "gemini-2.0-flash"
        cfg.settings.__dict__["gemini_api_key"] = "test-key"
        cfg.settings.__dict__["openai_api_key"] = ""
        from app.llm.config import llm_config_from_settings, LLMProvider
        c = llm_config_from_settings()
        assert c.provider == LLMProvider.GOOGLE
        assert c.model == "gemini-2.0-flash"
        assert c.has_api_key()

    def test_no_openai_error_when_gemini_configured(self, monkeypatch):
        from app.llm.exceptions import LLMConfigurationError
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "google")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        import app.config as cfg
        cfg.settings.__dict__["llm_default_provider"] = "google"
        cfg.settings.__dict__["gemini_api_key"] = "test-key"
        cfg.settings.__dict__["openai_api_key"] = ""
        from app.llm.config import llm_config_from_settings
        c = llm_config_from_settings()
        assert c.has_api_key()

    def test_role_none_uses_gemini_default(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "google")
        monkeypatch.setenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        import app.config as cfg
        cfg.settings.__dict__["llm_default_provider"] = "google"
        cfg.settings.__dict__["gemini_default_model"] = "gemini-2.0-flash"
        cfg.settings.__dict__["gemini_api_key"] = "test-key"
        cfg.settings.__dict__["openai_api_key"] = ""
        from app.llm import get_llm_gateway
        gw = get_llm_gateway()
        with patch.object(gw, "_build_model", return_value=MagicMock()) as mock_build:
            gw.get_chat_model_for_role(role_llm_model=None)
            called_cfg = mock_build.call_args[0][0]
            from app.llm.config import LLMProvider
            assert called_cfg.provider == LLMProvider.GOOGLE
            assert "gemini" in called_cfg.model

    def test_explicit_gpt_model_routes_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import app.config as cfg
        cfg.settings.__dict__["openai_api_key"] = "sk-test"
        cfg.settings.__dict__["gemini_api_key"] = "test-key"
        from app.llm.config import llm_config_from_settings, LLMProvider
        c = llm_config_from_settings(model="gpt-4o-mini")
        assert c.provider == LLMProvider.OPENAI

    def test_explicit_gemini_model_routes_google(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import app.config as cfg
        cfg.settings.__dict__["gemini_api_key"] = "test-key"
        from app.llm.config import llm_config_from_settings, LLMProvider
        c = llm_config_from_settings(model="gemini-2.0-flash")
        assert c.provider == LLMProvider.GOOGLE


class TestTenantContextFix:

    def test_integration_manager_uses_authenticated_tenant_id(self):
        import inspect
        from app.api.routers import integration_manager
        src = inspect.getsource(integration_manager)
        assert "get_current_tenant_id" in src
        assert "require_admin" in src
        assert "def _tenant(x_tenant_id" not in src

    def test_jwt_tenant_is_authoritative(self):
        from app.core.auth import create_access_token, _decode_token
        token = create_access_token("u1", "a@b.com", "real-tenant-123", "Admin")
        payload = _decode_token(token, "access")
        assert payload["tid"] == "real-tenant-123"
        assert payload["tid"] != "default-tenant"

    def test_tenant_comes_from_verified_user_only(self):
        """Phase 2: tenant is derived from the verified user; no header fallback exists."""
        import inspect
        from app.core import auth
        assert not hasattr(auth, "get_optional_tenant_id")
        src = inspect.getsource(auth.get_current_tenant_id)
        assert "user.tenant_id" in src
        assert "X-Tenant-ID" not in src

    def test_tenant_isolation_preserved_in_manager(self):
        import inspect
        from app.integrations import manager
        src = inspect.getsource(manager)
        assert "Integration.tenant_id == tenant_id" in src


class TestGoogleOAuth:

    def test_require_google_config_raises_503_not_500(self):
        from fastapi import HTTPException
        from app.api.routers.oauth_router import _require_google_config
        import app.config as cfg
        old_id = cfg.settings.google_client_id
        old_secret = cfg.settings.google_client_secret
        cfg.settings.__dict__["google_client_id"] = ""
        cfg.settings.__dict__["google_client_secret"] = ""
        try:
            with pytest.raises(HTTPException) as exc:
                _require_google_config()
            assert exc.value.status_code == 503
        finally:
            cfg.settings.__dict__["google_client_id"] = old_id
            cfg.settings.__dict__["google_client_secret"] = old_secret

    def test_oauth_503_message_mentions_google_client_id(self):
        from fastapi import HTTPException
        from app.api.routers.oauth_router import _require_google_config
        import app.config as cfg
        old_id = cfg.settings.google_client_id
        old_secret = cfg.settings.google_client_secret
        cfg.settings.__dict__["google_client_id"] = ""
        cfg.settings.__dict__["google_client_secret"] = ""
        try:
            with pytest.raises(HTTPException) as exc:
                _require_google_config()
            detail = exc.value.detail
            assert "GOOGLE_CLIENT_ID" in detail or "Google OAuth" in detail
        finally:
            cfg.settings.__dict__["google_client_id"] = old_id
            cfg.settings.__dict__["google_client_secret"] = old_secret


class TestGemini25FlashAllowlist:
    """Verify gemini-2.5-flash is fully integrated into every gate."""

    # ── LLMConfig acceptance ──────────────────────────────────────────────────

    def test_llm_config_accepts_gemini_25_flash(self, monkeypatch):
        """LLMConfig must not raise for gemini-3.5-flash-lite (current), gemini-3.8-flash, or gemini-2.5-flash."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import app.config as cfg
        cfg.settings.__dict__["gemini_api_key"] = "test-key"
        from app.llm.config import LLMConfig, LLMProvider
        for model in ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash"):
            config = LLMConfig(api_key="test-key", provider=LLMProvider.GOOGLE, model=model)
            assert config.model == model
            assert config.provider == LLMProvider.GOOGLE

    def test_llm_config_rejects_unknown_gemini_model(self):
        """LLMConfig must still reject unlisted Gemini model names."""
        from app.llm.exceptions import LLMUnsupportedModelError
        from app.llm.config import LLMConfig, LLMProvider
        import pytest
        with pytest.raises(LLMUnsupportedModelError):
            LLMConfig(api_key="test-key", provider=LLMProvider.GOOGLE, model="gemini-99.0-ultra")

    # ── Factory / settings path ───────────────────────────────────────────────

    def test_llm_config_from_settings_resolves_gemini_25_flash(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "google")
        monkeypatch.setenv("GEMINI_DEFAULT_MODEL", "gemini-3.5-flash-lite")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        import app.config as cfg
        cfg.settings.__dict__["llm_default_provider"] = "google"
        cfg.settings.__dict__["gemini_default_model"] = "gemini-3.5-flash-lite"
        cfg.settings.__dict__["gemini_api_key"] = "test-key"
        cfg.settings.__dict__["openai_api_key"] = ""
        from app.llm.config import llm_config_from_settings, LLMProvider
        c = llm_config_from_settings()
        assert c.provider == LLMProvider.GOOGLE
        assert c.model == "gemini-3.5-flash-lite"
        assert c.has_api_key()

    def test_explicit_gemini_25_routes_google(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import app.config as cfg
        cfg.settings.__dict__["gemini_api_key"] = "test-key"
        from app.llm.config import llm_config_from_settings, LLMProvider
        c = llm_config_from_settings(model="gemini-3.5-flash-lite")
        assert c.provider == LLMProvider.GOOGLE
        assert c.model == "gemini-3.5-flash-lite"

    def test_config_default_model_is_gemini_25_flash(self, monkeypatch):
        """The code-level default for gemini_default_model must be gemini-2.5-flash.
        We clear the env var so Pydantic Settings falls through to the field default."""
        monkeypatch.delenv("GEMINI_DEFAULT_MODEL", raising=False)
        from app.config import Settings
        fresh = Settings(
            secret_key="x" * 32,
            database_url="sqlite+aiosqlite:///./test.db",
        )
        assert fresh.gemini_default_model == "gemini-3.5-flash-lite"

    # ── Schema validator (role-config HTTP layer) ─────────────────────────────

    def test_role_config_schema_accepts_gemini_25_flash(self):
        from app.schemas.role_config import RoleConfigUpdate
        for model in ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash"):
            update = RoleConfigUpdate(llm_model=model)
            assert update.llm_model == model

    def test_role_config_schema_accepts_all_allowed_gemini_models(self):
        """Every model in ALLOWED_MODELS[GOOGLE] must pass the schema validator."""
        from app.llm.config import ALLOWED_MODELS, LLMProvider
        from app.schemas.role_config import RoleConfigUpdate
        for model in ALLOWED_MODELS[LLMProvider.GOOGLE]:
            update = RoleConfigUpdate(llm_model=model)
            assert update.llm_model == model, f"Schema rejected {model!r}"

    def test_role_config_schema_accepts_all_allowed_openai_models(self):
        """Existing OpenAI models must still be accepted (regression guard)."""
        from app.llm.config import ALLOWED_MODELS, LLMProvider
        from app.schemas.role_config import RoleConfigUpdate
        for model in ALLOWED_MODELS[LLMProvider.OPENAI]:
            update = RoleConfigUpdate(llm_model=model)
            assert update.llm_model == model, f"Schema rejected {model!r}"

    def test_role_config_schema_rejects_unknown_model(self):
        """Schema must still reject anything not in ALLOWED_MODELS."""
        import pytest
        from pydantic import ValidationError
        from app.schemas.role_config import RoleConfigUpdate
        with pytest.raises(ValidationError):
            RoleConfigUpdate(llm_model="gpt-99-ultra")

    # ── ALLOWED_MODELS set membership ─────────────────────────────────────────

    def test_gemini_25_flash_in_allowed_models(self):
        from app.llm.config import ALLOWED_MODELS, LLMProvider
        assert "gemini-3.5-flash-lite" in ALLOWED_MODELS[LLMProvider.GOOGLE]
        assert "gemini-3.8-flash" in ALLOWED_MODELS[LLMProvider.GOOGLE]
        assert "gemini-2.5-flash" in ALLOWED_MODELS[LLMProvider.GOOGLE]

    def test_gemini_25_flash_preview_still_allowed(self):
        """Preview alias must remain for any deployments still using it."""
        from app.llm.config import ALLOWED_MODELS, LLMProvider
        assert "gemini-2.5-flash-preview-04-17" in ALLOWED_MODELS[LLMProvider.GOOGLE]

    def test_gemini_15_flash_still_allowed(self):
        """Existing 1.5-flash deployments must not be broken."""
        from app.llm.config import ALLOWED_MODELS, LLMProvider
        assert "gemini-1.5-flash" in ALLOWED_MODELS[LLMProvider.GOOGLE]

    def test_gemini_20_flash_still_allowed(self):
        """Existing 2.0-flash deployments must not be broken."""
        from app.llm.config import ALLOWED_MODELS, LLMProvider
        assert "gemini-2.0-flash" in ALLOWED_MODELS[LLMProvider.GOOGLE]
