"""
EAAWP Application Configuration

All settings are read from environment variables / .env file.
Never hardcode credentials here.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    environment: str = "development"
    app_name: str = "EAAWP API"
    app_version: str = "0.2.0"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./eaawp.db"
    # Log every SQL statement (parameters stay hidden). Debugging aid only.
    sql_echo: bool = False

    # ── Security ──────────────────────────────────────────────────────────────
    secret_key: str = "dev-insecure-key-replace-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    refresh_token_expire_days: int = 30

    # Public-endpoint abuse protection (in-process, per API worker).
    rate_limit_enabled: bool = True
    # Number of reverse proxies in front of the API whose X-Forwarded-For entry
    # may be trusted.  0 = ignore the header and use the socket peer address.
    trusted_proxy_count: int = 0
    registration_enabled: bool = True            # set false to close self-service sign-up
    registration_rate_limit: int = 5             # new companies per IP ...
    registration_rate_window_seconds: int = 3600  # ... per window
    registration_daily_cap: int = 500            # new companies per process per 24h
    login_rate_limit: int = 30                   # login attempts per IP ...
    login_rate_window_seconds: int = 60          # ... per window
    login_max_failures: int = 5                  # failed logins per (IP, company, email) ...
    login_failure_window_seconds: int = 900      # ... before a 15 minute lockout
    refresh_rate_limit: int = 60                 # refresh/logout calls per IP ...
    refresh_rate_window_seconds: int = 60        # ... per window
    oauth_callback_rate_limit: int = 30
    oauth_callback_rate_window_seconds: int = 60
    # Optional JWT audience / issuer.  When set they are written into new tokens
    # and REQUIRED on every token presented.
    jwt_issuer: str = ""
    jwt_audience: str = ""
    # Optional dedicated key for encrypting stored integration credentials.
    # When empty the key is derived from SECRET_KEY (previous behaviour).
    encryption_key: str = ""
    allow_private_mcp_hosts: bool = False  # dev/test only: let MCP servers live on loopback/private addresses (default: public only)
    allow_private_db_hosts: bool = False   # production only: permit loopback/private database hosts (see services/outbound_guard.py)

    # ── LLM ───────────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    # Default model used by the LLM Gateway when no role-specific model is set.
    # Must be an entry in app.llm.config.ALLOWED_MODELS[LLMProvider.OPENAI].
    llm_default_model: str = "gpt-4o-mini"
    # Gemini embedding model for RAG document indexing and retrieval.
    # Both indexing and retrieval must use the same model — changing this
    # after documents are indexed requires full re-indexing of all chunks.
    # Available confirmed models (3072 dims each):
    #   models/gemini-embedding-001  — stable
    #   models/gemini-embedding-2    — current recommended
    gemini_embedding_model: str = "models/gemini-embedding-2"
    # Legacy alias — kept so any code that reads embedding_model doesn't crash.
    embedding_model: str = "models/gemini-embedding-2"

    # ── Google Gemini API ─────────────────────────────────────────────────────
    # Get from https://aistudio.google.com/app/apikey
    # Used by LLMProvider.GOOGLE (GeminiProvider).
    # If set, Gemini models are available alongside OpenAI models.
    gemini_api_key: str = ""
    # Default Gemini model — used when llm_default_provider=google
    # Override via GEMINI_DEFAULT_MODEL env var.
    # gemini-3.5-flash-lite is the current default: low-latency, cost-effective.
    gemini_default_model: str = "gemini-3.5-flash-lite"
    # Set to "google" to make Gemini the default provider for all agents
    # Leave empty or "openai" to keep OpenAI as default
    llm_default_provider: str = "openai"

    # ── Google OAuth 2.0 (Phase 4 — Google Search Console) ────────────────────
    # Register at https://console.cloud.google.com/ → APIs & Services → Credentials
    # Required scope: https://www.googleapis.com/auth/webmasters.readonly
    google_client_id: str = ""
    google_client_secret: str = ""
    # Must match exactly what is registered in the Google Cloud Console.
    google_redirect_uri: str = "http://localhost:8000/api/v1/oauth/google/callback"

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
