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
