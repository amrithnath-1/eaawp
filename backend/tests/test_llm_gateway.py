"""
EAAWP LLM Gateway — Phase 1 Test Suite

Covers every required scenario from the Phase 1 specification:

 1.  Gateway creates the configured OpenAI model.
 2.  Default model behaviour remains unchanged (gpt-4o-mini, temperature=0).
 3.  Invalid provider is rejected.
 4.  Invalid/unapproved model is rejected.
 5.  Invalid temperature/configuration is rejected.
 6.  Missing API key produces a controlled configuration error.
 7.  API key is never present in returned configuration objects.
 8.  Existing engine LLM execution still works (DynamicAgentEngine).
 9.  Existing planner LLM execution still works (_generate_plan, _synthesise_response).
10.  Tool binding still works (bind_tools preserved).
11.  Tenant/role model selection does not bypass validation.
12.  Existing LLM call sites no longer contain unnecessary duplicate config logic.

Additional coverage:
 A.  LLMConfig is immutable after construction.
 B.  safe_dict() / __repr__() never expose the key.
 C.  Factory get_provider() raises on unregistered provider.
 D.  LLMGateway.health() returns safe status without making a live API call.
 E.  get_chat_model_for_role() falls back to default when role model is None.
 F.  LLM status router returns correct shape and never leaks the key.
 G.  Content service _llm uses gateway (no direct ChatOpenAI import).
 H.  Config interpreter uses gateway (no direct ChatOpenAI import).
 I.  llm_config_from_settings reads settings.llm_default_model correctly.
 J.  AgentBlueprint.llm_model field is optional and defaults to None.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_blueprint(
    *,
    tools: list[str] | None = None,
    llm_model: str | None = None,
) -> "AgentBlueprint":
    from app.schemas.blueprint import AgentBlueprint
    return AgentBlueprint(
        agent_id="test-agent",
        role_name="Digital Marketing Manager",
        system_persona="You are the test DMM.",
        allowed_tools=tools or [],
        guarded_tools=[],
        tenant_id="tenant-test",
        llm_model=llm_model,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Gateway creates the configured OpenAI model
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatewayCreatesOpenAIModel:
    def test_get_chat_model_returns_chat_openai_instance(self, monkeypatch):
        """Gateway.get_chat_model() returns a ChatOpenAI-compatible model."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-001")
        # Reset the gateway singleton so it picks up the new env var
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        from langchain_openai import ChatOpenAI

        gateway = get_llm_gateway()
        model = gateway.get_chat_model()
        assert isinstance(model, ChatOpenAI)

    def test_get_chat_model_with_explicit_model_name(self, monkeypatch):
        """Gateway returns ChatOpenAI configured with the requested model."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-001")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        from langchain_openai import ChatOpenAI

        gateway = get_llm_gateway()
        model = gateway.get_chat_model(model="gpt-4o")
        assert isinstance(model, ChatOpenAI)
        # Verify the model attribute was passed through
        assert model.model_name == "gpt-4o"

    def test_provider_factory_returns_openai_provider(self):
        """Factory maps LLMProvider.OPENAI to OpenAIProvider."""
        from app.llm.config import LLMProvider
        from app.llm.factory import get_provider
        from app.llm.providers.openai_provider import OpenAIProvider

        provider = get_provider(LLMProvider.OPENAI)
        assert isinstance(provider, OpenAIProvider)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Default model behaviour remains unchanged
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefaultModelBehaviour:
    def test_default_model_is_gpt4o_mini(self):
        """Application default is gpt-4o-mini — must not be silently changed."""
        from app.llm.config import DEFAULT_MODEL
        assert DEFAULT_MODEL == "gpt-4o-mini"

    def test_default_temperature_is_zero(self):
        """Default temperature is 0.0 for deterministic behaviour."""
        from app.llm.config import DEFAULT_TEMPERATURE
        assert DEFAULT_TEMPERATURE == 0.0

    def test_default_provider_is_openai(self):
        """Default provider is OpenAI."""
        from app.llm.config import DEFAULT_PROVIDER, LLMProvider
        assert DEFAULT_PROVIDER == LLMProvider.OPENAI

    def test_llm_config_defaults(self, monkeypatch):
        """LLMConfig built with no overrides uses gpt-4o-mini at temperature 0."""
        from app.llm.config import LLMConfig, LLMProvider
        cfg = LLMConfig(api_key="sk-test", model="gpt-4o-mini")
        assert cfg.model == "gpt-4o-mini"
        assert cfg.temperature == 0.0
        assert cfg.provider == LLMProvider.OPENAI

    def test_gateway_model_matches_default(self, monkeypatch):
        """Model produced by gateway with no overrides is gpt-4o-mini."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-default")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        model = get_llm_gateway().get_chat_model()
        assert model.model_name == "gpt-4o-mini"

    def test_settings_llm_default_model_is_gpt4o_mini(self):
        """settings.llm_default_model default is gpt-4o-mini."""
        from app.config import Settings
        s = Settings(openai_api_key="sk-test")
        assert s.llm_default_model == "gpt-4o-mini"

    def test_content_service_temperature_is_0_7(self, monkeypatch):
        """Content service passes temperature=0.7 through gateway — intentional."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-content")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        model = get_llm_gateway().get_chat_model(temperature=0.7)
        assert model.temperature == 0.7


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Invalid provider is rejected
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidProviderRejected:
    def test_unknown_provider_string_raises_validation_error(self):
        """LLMConfig with unknown provider raises ValueError."""
        from pydantic import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            from app.llm.config import LLMConfig
            LLMConfig(api_key="sk-test", provider="anthropic", model="claude-3")

    def test_factory_unregistered_provider_raises(self):
        """get_provider() with an unregistered provider raises LLMProviderError."""
        from app.llm.exceptions import LLMProviderError
        from app.llm.config import LLMProvider

        # Create a fake provider value not in the registry
        # We patch _REGISTRY to simulate missing registration
        import app.llm.factory as factory_mod
        original = dict(factory_mod._REGISTRY)
        factory_mod._REGISTRY.clear()
        try:
            with pytest.raises(LLMProviderError, match="No implementation registered"):
                factory_mod.get_provider(LLMProvider.OPENAI)
        finally:
            factory_mod._REGISTRY.update(original)

    def test_invalid_provider_never_reaches_openai(self, monkeypatch):
        """A bad provider string never triggers any network call."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from pydantic import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            from app.llm.config import LLMConfig
            LLMConfig(api_key="sk-test", provider="fakeprovider", model="gpt-4o-mini")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Invalid / unapproved model is rejected
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidModelRejected:
    def test_unknown_model_raises_unsupported_model_error(self):
        """Model not in ALLOWED_MODELS raises LLMUnsupportedModelError."""
        from app.llm.exceptions import LLMUnsupportedModelError
        with pytest.raises(LLMUnsupportedModelError):
            from app.llm.config import LLMConfig
            LLMConfig(api_key="sk-test", model="gpt-99-ultra-secret")

    def test_arbitrary_model_string_rejected(self):
        """Arbitrary model strings are rejected regardless of plausibility."""
        from app.llm.exceptions import LLMUnsupportedModelError
        with pytest.raises(LLMUnsupportedModelError):
            from app.llm.config import LLMConfig
            LLMConfig(api_key="sk-test", model="../../etc/passwd")

    def test_all_allowed_models_accepted(self):
        """Every model in ALLOWED_MODELS can be used without error."""
        from app.llm.config import ALLOWED_MODELS, LLMConfig, LLMProvider
        for model_name in ALLOWED_MODELS[LLMProvider.OPENAI]:
            cfg = LLMConfig(api_key="sk-test", model=model_name)
            assert cfg.model == model_name

    def test_gateway_rejects_unapproved_model(self, monkeypatch):
        """Gateway.get_chat_model(model='bad-model') raises LLMUnsupportedModelError."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-model")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm.exceptions import LLMUnsupportedModelError
        with pytest.raises(LLMUnsupportedModelError):
            from app.llm import get_llm_gateway
            get_llm_gateway().get_chat_model(model="gpt-1-turbo-hacked")

    def test_role_model_selection_validated(self, monkeypatch):
        """get_chat_model_for_role() with a non-allowed model raises."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-role-model")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm.exceptions import LLMUnsupportedModelError
        with pytest.raises(LLMUnsupportedModelError):
            from app.llm import get_llm_gateway
            get_llm_gateway().get_chat_model_for_role(role_llm_model="gpt-injected-by-frontend")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Invalid temperature / configuration is rejected
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidConfigurationRejected:
    def test_temperature_above_2_rejected(self):
        """Temperature > 2.0 is rejected by Pydantic validation."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            from app.llm.config import LLMConfig
            LLMConfig(api_key="sk-test", model="gpt-4o-mini", temperature=3.0)

    def test_temperature_below_0_rejected(self):
        """Negative temperature is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            from app.llm.config import LLMConfig
            LLMConfig(api_key="sk-test", model="gpt-4o-mini", temperature=-0.1)

    def test_temperature_boundary_zero_accepted(self):
        """Temperature exactly 0.0 is valid."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key="sk-test", model="gpt-4o-mini", temperature=0.0)
        assert cfg.temperature == 0.0

    def test_temperature_boundary_two_accepted(self):
        """Temperature exactly 2.0 is valid."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key="sk-test", model="gpt-4o-mini", temperature=2.0)
        assert cfg.temperature == 2.0

    def test_max_tokens_below_one_rejected(self):
        """max_tokens < 1 is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            from app.llm.config import LLMConfig
            LLMConfig(api_key="sk-test", model="gpt-4o-mini", max_tokens=0)

    def test_timeout_below_one_rejected(self):
        """timeout < 1 is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            from app.llm.config import LLMConfig
            LLMConfig(api_key="sk-test", model="gpt-4o-mini", timeout=0)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Missing API key produces a controlled configuration error
# ═══════════════════════════════════════════════════════════════════════════════

class TestMissingApiKeyError:
    def test_empty_api_key_raises_configuration_error(self, monkeypatch):
        """llm_config_from_settings() with both keys empty raises LLMConfigurationError."""
        import app.config as cfg_mod
        original_openai = cfg_mod.settings.openai_api_key
        original_gemini = cfg_mod.settings.gemini_api_key
        # Clear both keys so neither fallback is available
        cfg_mod.settings.__dict__["openai_api_key"] = ""
        cfg_mod.settings.__dict__["gemini_api_key"] = ""

        from app.llm.config import llm_config_from_settings
        from app.llm.exceptions import LLMConfigurationError
        try:
            with pytest.raises(LLMConfigurationError):
                llm_config_from_settings()
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original_openai
            cfg_mod.settings.__dict__["gemini_api_key"] = original_gemini

    def test_whitespace_only_api_key_raises(self, monkeypatch):
        """Whitespace-only API key is treated as missing."""
        import app.config as cfg_mod
        original_key = cfg_mod.settings.openai_api_key
        cfg_mod.settings.__dict__["openai_api_key"] = "   "

        from app.llm.config import llm_config_from_settings
        from app.llm.exceptions import LLMConfigurationError
        try:
            with pytest.raises(LLMConfigurationError):
                llm_config_from_settings()
        finally:
            cfg_mod.settings.__dict__["openai_api_key"] = original_key

    def test_gateway_health_reports_not_ready_without_key(self):
        """LLMGateway.health() reports is_ready=False when key is absent."""
        from app.llm.gateway import LLMGateway
        from app.llm.exceptions import LLMConfigurationError

        # Build a fresh gateway instance directly with no key configured.
        # Patch llm_config_from_settings so this gateway never gets a valid config.
        with patch(
            "app.llm.gateway.llm_config_from_settings",
            side_effect=LLMConfigurationError("OPENAI_API_KEY is not configured."),
        ):
            gw = LLMGateway()

        health = gw.health()
        assert health.is_ready is False
        assert health.api_key_present is False
        assert health.error is not None

    def test_has_api_key_false_for_empty(self):
        """LLMConfig.has_api_key() returns False for empty key."""
        from app.llm.config import LLMConfig
        # Direct construction bypassing llm_config_from_settings
        cfg = LLMConfig(api_key="", model="gpt-4o-mini")
        assert cfg.has_api_key() is False

    def test_has_api_key_true_for_valid_key(self):
        """LLMConfig.has_api_key() returns True for a non-empty key."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key="sk-real-key", model="gpt-4o-mini")
        assert cfg.has_api_key() is True


# ═══════════════════════════════════════════════════════════════════════════════
# 7. API key is NEVER present in returned configuration objects
# ═══════════════════════════════════════════════════════════════════════════════

class TestApiKeyNeverExposed:
    REAL_KEY = "sk-super-secret-key-that-must-not-appear"

    def test_repr_does_not_contain_key(self):
        """LLMConfig.__repr__() never contains the API key value."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key=self.REAL_KEY, model="gpt-4o-mini")
        assert self.REAL_KEY not in repr(cfg)
        assert "REDACTED" in repr(cfg)

    def test_str_does_not_contain_key(self):
        """LLMConfig.__str__() never contains the API key value."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key=self.REAL_KEY, model="gpt-4o-mini")
        assert self.REAL_KEY not in str(cfg)

    def test_model_dump_does_not_contain_key(self):
        """LLMConfig.model_dump() does not include api_key."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key=self.REAL_KEY, model="gpt-4o-mini")
        dumped = cfg.model_dump()
        # The key must not appear as a value
        for v in dumped.values():
            assert v != self.REAL_KEY
        # The key must not appear as a field name
        assert "api_key" not in dumped

    def test_safe_dict_does_not_contain_key(self):
        """safe_dict() returns api_key_present (bool) not the actual key."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key=self.REAL_KEY, model="gpt-4o-mini")
        d = cfg.safe_dict()
        assert self.REAL_KEY not in str(d)
        assert d["api_key_present"] is True
        assert "api_key" not in d  # field name must not exist

    def test_health_status_does_not_contain_key(self, monkeypatch):
        """LLMGateway.health() result does not contain the API key."""
        monkeypatch.setenv("OPENAI_API_KEY", self.REAL_KEY)
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        health = get_llm_gateway().health()
        health_str = str(health)
        assert self.REAL_KEY not in health_str

    def test_llm_config_frozen_prevents_key_modification(self):
        """LLMConfig is frozen — public fields cannot be changed after creation."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key="sk-test", model="gpt-4o-mini")
        with pytest.raises(Exception):  # ValidationError or TypeError (frozen model)
            cfg.model = "gpt-4o"  # type: ignore[misc]

    def test_llm_status_router_schema_has_no_api_key_field(self):
        """LLMStatusResponse schema has api_key_present bool, not the key itself."""
        from app.api.routers.llm_gateway import LLMStatusResponse
        fields = LLMStatusResponse.model_fields
        assert "api_key" not in fields
        assert "api_key_present" in fields


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Existing engine LLM execution still works (DynamicAgentEngine)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEngineExecutionCompatibility:
    def test_engine_initialises_via_gateway(self, monkeypatch):
        """DynamicAgentEngine.__init__ succeeds and uses the gateway."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-engine-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.core.engine import DynamicAgentEngine
        bp = _make_blueprint(tools=["query_campaign_analytics"])
        engine = DynamicAgentEngine(blueprint=bp)
        assert engine._model is not None

    def test_engine_has_no_direct_chatopenai_import(self):
        """engine.py must not import ChatOpenAI directly."""
        import app.core.engine as engine_mod
        source = inspect.getsource(engine_mod)
        assert "from langchain_openai import ChatOpenAI" not in source
        assert "langchain_openai" not in source or "get_llm_gateway" in source

    @pytest.mark.asyncio
    async def test_engine_execute_with_mocked_model(self, monkeypatch):
        """Engine.execute() works end-to-end with a mocked model response."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-engine-exec-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        # Mock the model so we never hit OpenAI
        mock_response = MagicMock()
        mock_response.content = "Test response from mocked model."
        mock_response.tool_calls = []
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        mock_model.bind_tools = MagicMock(return_value=mock_model)

        with patch("app.llm.gateway.LLMGateway.get_chat_model_for_role",
                   return_value=mock_model):
            from app.core.engine import DynamicAgentEngine
            bp = _make_blueprint(tools=[])
            engine = DynamicAgentEngine(blueprint=bp)
            result = await engine.execute(user_prompt="Hello test")

        assert result.message == "Test response from mocked model."
        assert result.session_id is not None

    def test_engine_tool_map_populated_correctly(self, monkeypatch):
        """Engine builds _tool_map from blueprint allowed_tools."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-engine-tools-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.core.engine import DynamicAgentEngine
        from app.tools.registry import MASTER_TOOL_REGISTRY
        # Use a tool we know is in the registry
        known_tools = list(MASTER_TOOL_REGISTRY.keys())[:1]
        bp = _make_blueprint(tools=known_tools)
        engine = DynamicAgentEngine(blueprint=bp)
        assert set(known_tools).issubset(set(engine._tool_map.keys()))

    def test_engine_blueprint_llm_model_field_accepted(self, monkeypatch):
        """AgentBlueprint.llm_model is optional and accepted by the engine."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-engine-model-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.core.engine import DynamicAgentEngine
        bp = _make_blueprint(tools=[], llm_model="gpt-4o")
        engine = DynamicAgentEngine(blueprint=bp)
        assert engine.blueprint.llm_model == "gpt-4o"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Existing planner LLM execution still works
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlannerExecutionCompatibility:
    def test_planner_has_no_direct_chatopenai_import(self):
        """planner.py must not import ChatOpenAI directly."""
        import app.services.planner as planner_mod
        source = inspect.getsource(planner_mod)
        assert "from langchain_openai import ChatOpenAI" not in source

    def test_generate_plan_function_exists(self):
        """_generate_plan() is importable from planner."""
        from app.services.planner import _generate_plan
        assert callable(_generate_plan)

    def test_synthesise_response_function_exists(self):
        """_synthesise_response() is importable from planner."""
        from app.services.planner import _synthesise_response
        assert callable(_synthesise_response)

    @pytest.mark.asyncio
    async def test_generate_plan_with_mocked_gateway(self, monkeypatch):
        """_generate_plan() calls gateway and parses JSON plan correctly."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-planner-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        plan_json = '{"objective":"Test","steps":[{"step_index":0,"step_type":"analysis","description":"Analyse","tool_name":null,"arguments":{},"depends_on":[]}]}'
        mock_resp = MagicMock()
        mock_resp.content = plan_json
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_resp)

        with patch("app.llm.gateway.LLMGateway.get_chat_model", return_value=mock_model):
            from app.services.planner import _generate_plan
            bp = _make_blueprint()
            plan = await _generate_plan(
                user_prompt="Analyse campaign performance",
                blueprint=bp,
                system_persona="You are the DMM.",
                data_context_block="",
                rag_context="",
            )

        assert plan is not None
        assert plan.objective == "Test"
        assert len(plan.steps) == 1

    @pytest.mark.asyncio
    async def test_synthesise_response_with_mocked_gateway(self, monkeypatch):
        """_synthesise_response() returns the LLM's text content."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-synth-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        mock_resp = MagicMock()
        mock_resp.content = "Synthesis result text."
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_resp)

        with patch("app.llm.gateway.LLMGateway.get_chat_model", return_value=mock_model):
            from app.services.planner import _synthesise_response
            bp = _make_blueprint()
            result = await _synthesise_response(
                objective="Test objective",
                step_results={0: "Step 0 result"},
                blueprint=bp,
            )

        assert result == "Synthesis result text."


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Tool binding still works
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolBindingPreserved:
    def test_engine_calls_bind_tools_when_tools_present(self, monkeypatch):
        """Engine calls .bind_tools() on the model when tools are present."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-bind-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        mock_bound = MagicMock()
        mock_model = MagicMock()
        mock_model.bind_tools = MagicMock(return_value=mock_bound)

        with patch("app.llm.gateway.LLMGateway.get_chat_model_for_role",
                   return_value=mock_model):
            from app.core.engine import DynamicAgentEngine
            from app.tools.registry import MASTER_TOOL_REGISTRY
            tool_key = next(iter(MASTER_TOOL_REGISTRY))
            bp = _make_blueprint(tools=[tool_key])
            engine = DynamicAgentEngine(blueprint=bp)

        mock_model.bind_tools.assert_called_once()
        assert engine._model is mock_bound

    def test_engine_skips_bind_tools_when_no_tools(self, monkeypatch):
        """Engine uses the raw model (no bind_tools) when allowed_tools is empty."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-nobind-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        mock_model = MagicMock()
        mock_model.bind_tools = MagicMock()

        with patch("app.llm.gateway.LLMGateway.get_chat_model_for_role",
                   return_value=mock_model):
            from app.core.engine import DynamicAgentEngine
            bp = _make_blueprint(tools=[])
            engine = DynamicAgentEngine(blueprint=bp)

        mock_model.bind_tools.assert_not_called()
        assert engine._model is mock_model

    def test_get_chat_model_supports_bind_tools(self, monkeypatch):
        """The model returned by gateway.get_chat_model() has .bind_tools()."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-bindmeth-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        model = get_llm_gateway().get_chat_model()
        assert hasattr(model, "bind_tools")
        assert callable(model.bind_tools)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Tenant / role model selection does not bypass validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestTenantRoleModelValidation:
    def test_role_model_in_allowlist_accepted(self, monkeypatch):
        """get_chat_model_for_role() with an allowed model works."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-role-valid")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        from langchain_openai import ChatOpenAI
        model = get_llm_gateway().get_chat_model_for_role(role_llm_model="gpt-4o")
        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "gpt-4o"

    def test_role_model_not_in_allowlist_rejected(self, monkeypatch):
        """get_chat_model_for_role() rejects models not in ALLOWED_MODELS."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-role-invalid")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        from app.llm.exceptions import LLMUnsupportedModelError
        with pytest.raises(LLMUnsupportedModelError):
            get_llm_gateway().get_chat_model_for_role(
                role_llm_model="gpt-injected-arbitrary-model"
            )

    def test_role_model_none_falls_back_to_default(self, monkeypatch):
        """get_chat_model_for_role(None) falls back to DEFAULT_MODEL."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-role-none")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        from app.llm.config import DEFAULT_MODEL
        model = get_llm_gateway().get_chat_model_for_role(role_llm_model=None)
        assert model.model_name == DEFAULT_MODEL

    def test_role_config_update_validator_matches_allowlist(self):
        """RoleConfigUpdate.validate_llm_model allows exactly the same set as ALLOWED_MODELS."""
        from app.llm.config import ALLOWED_MODELS, LLMProvider
        from pydantic import ValidationError

        gateway_allowed = ALLOWED_MODELS[LLMProvider.OPENAI]

        # Every allowed gateway model must pass schema validation
        for model_name in gateway_allowed:
            from app.schemas.role_config import RoleConfigUpdate
            obj = RoleConfigUpdate(llm_model=model_name)
            assert obj.llm_model == model_name

        # A model not in the gateway allowlist must fail schema validation
        with pytest.raises(ValidationError):
            from app.schemas.role_config import RoleConfigUpdate
            RoleConfigUpdate(llm_model="gpt-injected")

    def test_blueprint_llm_model_rejected_if_invalid(self, monkeypatch):
        """Blueprint with invalid llm_model causes gateway to reject at model creation time."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-bp-invalid")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.schemas.blueprint import AgentBlueprint
        from app.llm.exceptions import LLMUnsupportedModelError
        bp = AgentBlueprint(
            agent_id="test",
            role_name="Digital Marketing Manager",
            system_persona="Test",
            allowed_tools=[],
            guarded_tools=[],
            tenant_id="t1",
            llm_model="gpt-99-arbitrary",  # stored but not validated at schema level
        )
        from app.llm import get_llm_gateway
        with pytest.raises(LLMUnsupportedModelError):
            get_llm_gateway().get_chat_model_for_role(role_llm_model=bp.llm_model)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Existing call sites no longer contain duplicate config logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoDuplicateConfigLogic:
    def _source_of(self, module_path: str) -> str:
        mod = importlib.import_module(module_path)
        return inspect.getsource(mod)

    def test_engine_has_no_direct_chatopenai_init(self):
        """engine.py contains no ChatOpenAI() constructor call."""
        src = self._source_of("app.core.engine")
        assert "ChatOpenAI(" not in src

    def test_planner_has_no_direct_chatopenai_init(self):
        """planner.py contains no ChatOpenAI() constructor call."""
        src = self._source_of("app.services.planner")
        assert "ChatOpenAI(" not in src

    def test_config_interpreter_has_no_direct_chatopenai_init(self):
        """config_interpreter.py contains no ChatOpenAI() constructor call."""
        src = self._source_of("app.services.config_interpreter")
        assert "ChatOpenAI(" not in src

    def test_content_service_has_no_direct_chatopenai_init(self):
        """content_service.py contains no ChatOpenAI() constructor call."""
        src = self._source_of("app.services.content_service")
        assert "ChatOpenAI(" not in src

    def test_engine_imports_gateway(self):
        """engine.py imports from app.llm."""
        src = self._source_of("app.core.engine")
        assert "from app.llm import get_llm_gateway" in src

    def test_planner_imports_gateway(self):
        """planner.py imports from app.llm."""
        src = self._source_of("app.services.planner")
        assert "from app.llm import get_llm_gateway" in src

    def test_config_interpreter_imports_gateway(self):
        """config_interpreter.py imports from app.llm."""
        src = self._source_of("app.services.config_interpreter")
        assert "from app.llm import get_llm_gateway" in src

    def test_content_service_imports_gateway(self):
        """content_service.py imports from app.llm."""
        src = self._source_of("app.services.content_service")
        assert "from app.llm import get_llm_gateway" in src


# ═══════════════════════════════════════════════════════════════════════════════
# A. LLMConfig immutability
# ═══════════════════════════════════════════════════════════════════════════════

class TestLLMConfigImmutability:
    def test_config_is_frozen(self):
        """LLMConfig is frozen — any mutation raises."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key="sk-test", model="gpt-4o-mini")
        with pytest.raises(Exception):
            cfg.temperature = 1.0  # type: ignore[misc]

    def test_config_model_field_not_reassignable(self):
        """LLMConfig.model field cannot be changed after construction."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key="sk-test", model="gpt-4o-mini")
        with pytest.raises(Exception):
            cfg.model = "gpt-4o"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# B. safe_dict and repr never expose key
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafeRepresentations:
    KEY = "sk-absolutely-secret-99999"

    def test_safe_dict_fields(self):
        """safe_dict() contains exactly the expected keys."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key=self.KEY, model="gpt-4o-mini", temperature=0.5)
        d = cfg.safe_dict()
        assert set(d.keys()) == {"provider", "model", "temperature", "max_tokens",
                                   "timeout", "api_key_present"}

    def test_safe_dict_key_value_is_bool(self):
        """safe_dict()['api_key_present'] is a boolean."""
        from app.llm.config import LLMConfig
        cfg = LLMConfig(api_key=self.KEY, model="gpt-4o-mini")
        d = cfg.safe_dict()
        assert isinstance(d["api_key_present"], bool)
        assert d["api_key_present"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# D. LLMGateway.health() — no live API call
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatewayHealth:
    def test_health_returns_ready_with_key(self, monkeypatch):
        """health() returns is_ready=True when key is configured."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-health-test")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        health = get_llm_gateway().health()
        assert health.is_ready is True
        assert health.api_key_present is True
        assert health.error is None

    def test_health_includes_allowed_models(self, monkeypatch):
        """health() response includes the application allowed_models list."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-health-models")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        health = get_llm_gateway().health()
        assert "gpt-4o-mini" in health.allowed_models
        assert "gpt-4o" in health.allowed_models

    def test_health_never_makes_network_call(self, monkeypatch):
        """health() does not call any external API (no openai import touched)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-health-nonet")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway

        # Patch httpx / requests to fail if called — they should not be
        with patch("httpx.Client.send", side_effect=RuntimeError("NETWORK CALL FORBIDDEN")):
            with patch("httpx.AsyncClient.send", side_effect=RuntimeError("NETWORK CALL FORBIDDEN")):
                health = get_llm_gateway().health()
        assert health is not None  # reached without network call


# ═══════════════════════════════════════════════════════════════════════════════
# E. get_chat_model_for_role fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleModelFallback:
    def test_empty_string_falls_back_to_default(self, monkeypatch):
        """Empty string role model falls back to DEFAULT_MODEL."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback-empty")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.llm import get_llm_gateway
        from app.llm.config import DEFAULT_MODEL
        model = get_llm_gateway().get_chat_model_for_role(role_llm_model="")
        assert model.model_name == DEFAULT_MODEL


# ═══════════════════════════════════════════════════════════════════════════════
# G/H. Source-level: no langchain_openai in call sites
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoDirectLangchainOpenAIInCallSites:
    def test_engine_does_not_import_langchain_openai(self):
        """engine.py must not import from langchain_openai."""
        import app.core.engine as mod
        source = inspect.getsource(mod)
        assert "from langchain_openai" not in source

    def test_planner_does_not_import_langchain_openai(self):
        """planner.py must not import from langchain_openai."""
        import app.services.planner as mod
        source = inspect.getsource(mod)
        assert "from langchain_openai" not in source

    def test_config_interpreter_does_not_import_langchain_openai(self):
        """config_interpreter.py must not import from langchain_openai."""
        import app.services.config_interpreter as mod
        source = inspect.getsource(mod)
        assert "from langchain_openai" not in source

    def test_content_service_does_not_import_langchain_openai(self):
        """content_service.py must not import from langchain_openai."""
        import app.services.content_service as mod
        source = inspect.getsource(mod)
        assert "from langchain_openai" not in source


# ═══════════════════════════════════════════════════════════════════════════════
# I. llm_config_from_settings reads llm_default_model from settings
# ═══════════════════════════════════════════════════════════════════════════════

class TestLlmConfigFromSettings:
    def test_uses_settings_llm_default_model(self, monkeypatch):
        """llm_config_from_settings() uses settings.llm_default_model as default."""
        import app.config as cfg_mod
        original = cfg_mod.settings.llm_default_model
        cfg_mod.settings.__dict__["llm_default_model"] = "gpt-4o"
        cfg_mod.settings.__dict__["openai_api_key"] = "sk-settings-model-test"

        import app.llm.config as llm_cfg_mod
        # Reset module-level settings cache
        try:
            from app.llm.config import llm_config_from_settings
            cfg = llm_config_from_settings()
            assert cfg.model == "gpt-4o"
        finally:
            cfg_mod.settings.__dict__["llm_default_model"] = original

    def test_model_override_takes_precedence(self, monkeypatch):
        """Explicit model argument overrides settings.llm_default_model."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["openai_api_key"] = "sk-override-test"
        cfg_mod.settings.__dict__["llm_default_model"] = "gpt-4o-mini"

        from app.llm.config import llm_config_from_settings
        cfg = llm_config_from_settings(model="gpt-4o")
        assert cfg.model == "gpt-4o"


# ═══════════════════════════════════════════════════════════════════════════════
# J. AgentBlueprint.llm_model optional field
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentBlueprintLlmModelField:
    def test_blueprint_llm_model_defaults_to_none(self):
        """AgentBlueprint.llm_model defaults to None when not provided."""
        from app.schemas.blueprint import AgentBlueprint
        bp = AgentBlueprint(
            agent_id="x", role_name="Test", system_persona="P",
            tenant_id="t1",
        )
        assert bp.llm_model is None

    def test_blueprint_llm_model_can_be_set(self):
        """AgentBlueprint.llm_model can be set to an allowed model."""
        from app.schemas.blueprint import AgentBlueprint
        bp = AgentBlueprint(
            agent_id="x", role_name="Test", system_persona="P",
            tenant_id="t1", llm_model="gpt-4o",
        )
        assert bp.llm_model == "gpt-4o"

    def test_blueprint_without_llm_model_still_executes(self, monkeypatch):
        """Engine handles blueprint with llm_model=None gracefully."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-bp-none-model")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.core.engine import DynamicAgentEngine
        bp = _make_blueprint(tools=[], llm_model=None)
        engine = DynamicAgentEngine(blueprint=bp)
        assert engine._model is not None
