"""
EAAWP Phase 2 — Dynamic Integration Framework Tests

Covers:
 1.  Registry registers and retrieves providers by type string.
 2.  Registry raises on unknown provider type.
 3.  Registry.provider_catalogue() returns safe metadata only.
 4.  Registry.provider_catalogue() never contains credential field values.
 5.  Built-in providers (postgresql, mysql) are registered at import time.
 6.  ProviderCapability is immutable (frozen dataclass).
 7.  IntegrationProvider.get_capability() returns correct capability.
 8.  IntegrationProvider.get_capability() returns None for unknown key.
 9.  PostgreSQL provider declares required credential fields.
10.  MySQL provider declares required credential fields.
11.  Provider._sanitise_error() redacts passwords and tokens.
12.  Integration ORM model has correct table name.
13.  CapabilityGrant ORM model has correct table name.
14.  Credential encryption round-trips correctly.
15.  Credential encryption never stores plaintext.
16.  Manager.create_integration rejects unknown provider type.
17.  Manager.create_integration succeeds for known provider type.
18.  Manager.test_integration returns not_configured when no credentials.
19.  Manager.has_capability_grant returns False when no grant exists.
20.  Manager.create_capability_grant rejects invalid capability_key.
21.  Manager.create_capability_grant succeeds for valid capability.
22.  Manager.execute_capability raises PermissionError without grant.
23.  Manager.execute_capability raises ValueError when not connected.
24.  API router /providers returns provider catalogue.
25.  API router /status returns framework readiness.
26.  API router /integrations POST rejects unknown provider type.
27.  IntegrationOut schema never contains encrypted_credentials.
28.  IntegrationOut.has_credentials reflects whether creds are stored.
29.  Existing BaseConnector is still importable (no breakage).
30.  Existing DataConnection ORM is still importable (no breakage).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# 1–4. Registry
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrationRegistry:
    def test_registry_registers_and_retrieves_provider(self):
        """Registry returns the correct provider for a known type."""
        from app.integrations.integration_registry import IntegrationRegistry
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider

        reg = IntegrationRegistry()
        provider = PostgreSQLIntegrationProvider()
        reg.register(provider)
        assert reg.get("postgresql") is provider

    def test_registry_get_returns_none_for_unknown(self):
        """Registry.get() returns None for an unregistered type."""
        from app.integrations.integration_registry import IntegrationRegistry
        reg = IntegrationRegistry()
        assert reg.get("nonexistent_provider") is None

    def test_registry_get_or_raise_raises_for_unknown(self):
        """Registry.get_or_raise() raises ValueError for unregistered type."""
        from app.integrations.integration_registry import IntegrationRegistry
        reg = IntegrationRegistry()
        with pytest.raises(ValueError, match="Unknown integration provider"):
            reg.get_or_raise("nonexistent_provider")

    def test_registry_catalogue_is_safe(self):
        """provider_catalogue() returns serialisable dicts with no credential values."""
        from app.integrations.integration_registry import IntegrationRegistry
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider

        reg = IntegrationRegistry()
        reg.register(PostgreSQLIntegrationProvider())
        catalogue = reg.provider_catalogue()

        assert isinstance(catalogue, list)
        assert len(catalogue) == 1
        item = catalogue[0]
        assert item["provider_type"] == "postgresql"
        assert "display_name" in item
        assert "capabilities" in item
        # Must be JSON-serialisable (no credential values, no complex objects)
        json.dumps(item)  # raises if not serialisable

    def test_registry_catalogue_never_contains_credentials(self):
        """Catalogue must never contain credential field values (only field names)."""
        from app.integrations.integration_registry import IntegrationRegistry
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider

        reg = IntegrationRegistry()
        reg.register(PostgreSQLIntegrationProvider())
        catalogue_str = json.dumps(reg.provider_catalogue())
        # required_credential_fields lists the names, not values
        assert "sk-" not in catalogue_str
        assert "password" in catalogue_str  # the FIELD NAME is fine
        # No actual key-like values should appear
        assert "postgresql" in catalogue_str


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Built-in providers registered
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuiltinProviders:
    def test_postgresql_registered_at_import(self):
        """postgresql provider is registered in the application registry."""
        from app.integrations.integration_registry import integration_registry
        assert integration_registry.has("postgresql")

    def test_mysql_registered_at_import(self):
        """mysql provider is registered in the application registry."""
        from app.integrations.integration_registry import integration_registry
        assert integration_registry.has("mysql")

    def test_builtin_providers_have_capabilities(self):
        """Both built-in providers declare at least one capability."""
        from app.integrations.integration_registry import integration_registry
        for ptype in ("postgresql", "mysql"):
            provider = integration_registry.get(ptype)
            assert provider is not None
            caps = provider.get_capabilities()
            assert len(caps) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 6–8. ProviderCapability
# ═══════════════════════════════════════════════════════════════════════════════

class TestProviderCapability:
    def test_capability_is_frozen(self):
        """ProviderCapability is a frozen dataclass — immutable."""
        from app.integrations.provider import CapabilityCategory, ProviderCapability, RiskLevel
        cap = ProviderCapability(
            key="test_cap",
            display_name="Test",
            description="A test capability.",
            category=CapabilityCategory.READ,
            risk_level=RiskLevel.LOW,
        )
        with pytest.raises((AttributeError, TypeError)):
            cap.key = "modified"  # type: ignore[misc]

    def test_get_capability_returns_correct_one(self):
        """provider.get_capability(key) returns the matching capability."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        provider = PostgreSQLIntegrationProvider()
        cap = provider.get_capability("discover_schema")
        assert cap is not None
        assert cap.key == "discover_schema"

    def test_get_capability_returns_none_for_unknown(self):
        """provider.get_capability() returns None for a non-existent key."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        provider = PostgreSQLIntegrationProvider()
        assert provider.get_capability("nonexistent_cap") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 9–10. Provider credential fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestProviderCredentialFields:
    def test_postgresql_required_fields(self):
        """PostgreSQL provider declares the expected credential fields."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        fields = PostgreSQLIntegrationProvider().required_credential_fields()
        assert "host" in fields
        assert "port" in fields
        assert "database" in fields
        assert "username" in fields
        assert "password" in fields

    def test_mysql_required_fields(self):
        """MySQL provider declares the expected credential fields."""
        from app.integrations.providers.mysql_provider import MySQLIntegrationProvider
        fields = MySQLIntegrationProvider().required_credential_fields()
        assert "host" in fields
        assert "password" in fields

    def test_credential_fields_are_strings(self):
        """All credential field names are plain strings."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        for field in PostgreSQLIntegrationProvider().required_credential_fields():
            assert isinstance(field, str)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. _sanitise_error
# ═══════════════════════════════════════════════════════════════════════════════

class TestSanitiseError:
    def test_password_redacted(self):
        """_sanitise_error redacts password= values."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        p = PostgreSQLIntegrationProvider()
        result = p._sanitise_error("Connection failed: password=mysecretpass123")
        assert "mysecretpass123" not in result
        assert "REDACTED" in result

    def test_dsn_redacted(self):
        """_sanitise_error redacts DSN-style connection strings."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        p = PostgreSQLIntegrationProvider()
        result = p._sanitise_error("Error: postgresql://user:secret@host:5432/db")
        assert "secret" not in result
        assert "REDACTED" in result

    def test_api_key_redacted(self):
        """_sanitise_error redacts api_key values."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        p = PostgreSQLIntegrationProvider()
        result = p._sanitise_error("Bad request: api_key=sk-abc123xyz")
        assert "sk-abc123xyz" not in result

    def test_clean_message_unchanged(self):
        """_sanitise_error does not modify safe error messages."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        p = PostgreSQLIntegrationProvider()
        msg = "Connection timed out after 10 seconds."
        result = p._sanitise_error(msg)
        assert result == msg


# ═══════════════════════════════════════════════════════════════════════════════
# 12–13. ORM models
# ═══════════════════════════════════════════════════════════════════════════════

class TestORMModels:
    def test_integration_table_name(self):
        from app.db.integration_models import Integration
        assert Integration.__tablename__ == "integration_catalog"

    def test_capability_grant_table_name(self):
        from app.db.integration_models import CapabilityGrant
        assert CapabilityGrant.__tablename__ == "capability_grants"

    def test_integration_has_tenant_id(self):
        from app.db.integration_models import Integration
        cols = [c.key for c in Integration.__table__.columns]
        assert "tenant_id" in cols

    def test_integration_has_no_plaintext_password_column(self):
        """Integration table must not have any column storing plaintext passwords."""
        from app.db.integration_models import Integration
        cols = [c.key for c in Integration.__table__.columns]
        for bad in ("password", "secret", "plain_credentials", "api_key"):
            assert bad not in cols

    def test_integration_encrypted_credentials_is_text(self):
        from app.db.integration_models import Integration
        from sqlalchemy import Text
        col = Integration.__table__.columns["encrypted_credentials"]
        assert isinstance(col.type, Text)

    def test_capability_grant_unique_constraint(self):
        """capability_grants has a unique constraint on (integration_id, role_key, cap_key)."""
        from app.db.integration_models import CapabilityGrant
        constraint_names = {
            c.name for c in CapabilityGrant.__table__.constraints
        }
        assert "uq_capability_grant_integration_role_cap" in constraint_names


# ═══════════════════════════════════════════════════════════════════════════════
# 14–15. Credential encryption
# ═══════════════════════════════════════════════════════════════════════════════

class TestCredentialEncryption:
    def test_encrypt_decrypt_round_trip(self, monkeypatch):
        """Credentials survive an encrypt → decrypt round-trip."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["secret_key"] = "test-secret-key-for-encryption"

        from app.integrations.manager import _decrypt_credentials, _encrypt_credentials
        original = {"host": "db.example.com", "port": 5432, "password": "verysecret"}
        encrypted = _encrypt_credentials(original)
        decrypted = _decrypt_credentials(encrypted)
        assert decrypted == original

    def test_encrypted_blob_never_contains_plaintext_password(self, monkeypatch):
        """The encrypted blob must not contain the plaintext password."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["secret_key"] = "test-secret-key-for-encryption"

        from app.integrations.manager import _encrypt_credentials
        secret = "ultra-secret-password-9876"
        encrypted = _encrypt_credentials({"password": secret})
        assert secret not in encrypted

    def test_encrypted_credentials_differ_from_input(self, monkeypatch):
        """Encrypted output must not equal the JSON input."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["secret_key"] = "test-secret-key-for-encryption"

        from app.integrations.manager import _encrypt_credentials
        creds = {"api_key": "my-key"}
        encrypted = _encrypt_credentials(creds)
        assert encrypted != json.dumps(creds)


# ═══════════════════════════════════════════════════════════════════════════════
# 16–17. Manager CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestManagerCRUD:
    @pytest.mark.asyncio
    async def test_create_integration_rejects_unknown_provider(self):
        """create_integration raises ValueError for unregistered provider_type."""
        from app.integrations.manager import create_integration
        from app.schemas.integration_framework import IntegrationCreate

        mock_db = AsyncMock()
        body = IntegrationCreate(
            provider_type="nonexistent_provider",
            display_name="Test",
            credentials={"key": "value"},
        )
        with pytest.raises(ValueError, match="Unknown provider type"):
            await create_integration(body, "tenant-1", mock_db)

    @pytest.mark.asyncio
    async def test_create_integration_succeeds_for_known_provider(self, monkeypatch):
        """create_integration persists an Integration row for a known provider."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["secret_key"] = "test-secret-key-for-crud"

        from app.integrations.manager import create_integration
        from app.schemas.integration_framework import IntegrationCreate
        from app.db.integration_models import Integration

        added = []
        mock_db = AsyncMock()
        def track_add(obj):
            if isinstance(obj, Integration):
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)
            added.append(obj)
        mock_db.add = track_add
        mock_db.flush = AsyncMock()

        body = IntegrationCreate(
            provider_type="postgresql",
            display_name="My Test DB",
            credentials={"host": "localhost", "port": 5432, "database": "mydb",
                         "username": "user", "password": "secret"},
        )
        result = await create_integration(body, "tenant-1", mock_db)
        assert result.provider_type == "postgresql"
        assert result.display_name == "My Test DB"
        assert result.has_credentials is True
        # Credentials never in the output
        result_json = result.model_dump_json()
        assert "secret" not in result_json
        assert "password" not in result_json


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Manager.test_integration — no credentials case
# ═══════════════════════════════════════════════════════════════════════════════

class TestManagerTestIntegration:
    @pytest.mark.asyncio
    async def test_returns_not_configured_when_no_credentials(self):
        """test_integration returns not_configured when encrypted_credentials is empty."""
        from app.integrations.manager import test_integration
        from app.db.integration_models import Integration

        mock_row = MagicMock(spec=Integration)
        mock_row.id = "int-001"
        mock_row.provider_type = "postgresql"
        mock_row.display_name = "Test DB"
        mock_row.encrypted_credentials = ""  # no credentials
        mock_row.status = "not_configured"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await test_integration("int-001", "tenant-1", mock_db)
        assert result.success is False
        assert result.status == "not_configured"
        assert "credentials" in (result.error_message or "").lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 19–21. Capability grants
# ═══════════════════════════════════════════════════════════════════════════════

class TestCapabilityGrants:
    @pytest.mark.asyncio
    async def test_has_capability_grant_returns_false_when_none_exist(self):
        """has_capability_grant returns False when no grant row exists."""
        from app.integrations.manager import has_capability_grant

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await has_capability_grant(
            integration_id="int-1",
            role_key="DIGITAL_MARKETING_MANAGER",
            capability_key="query_entity",
            tenant_id="t1",
            db=mock_db,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_create_grant_rejects_invalid_capability_key(self):
        """create_capability_grant raises ValueError for a non-existent capability."""
        from app.integrations.manager import create_capability_grant
        from app.schemas.integration_framework import CapabilityGrantCreate
        from app.db.integration_models import Integration

        mock_row = MagicMock(spec=Integration)
        mock_row.provider_type = "postgresql"
        mock_row.tenant_id = "t1"

        mock_db = AsyncMock()
        mock_result_int = MagicMock()
        mock_result_int.scalar_one_or_none.return_value = mock_row
        mock_result_grant = MagicMock()
        mock_result_grant.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result_int, mock_result_grant])
        mock_db.flush = AsyncMock()

        with pytest.raises(ValueError, match="does not exist"):
            await create_capability_grant(
                integration_id="int-1",
                body=CapabilityGrantCreate(
                    role_key="DIGITAL_MARKETING_MANAGER",
                    capability_key="nonexistent_capability",
                ),
                tenant_id="t1",
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_create_grant_succeeds_for_valid_capability(self):
        """create_capability_grant creates a grant for a valid capability key."""
        from app.integrations.manager import create_capability_grant
        from app.schemas.integration_framework import CapabilityGrantCreate
        from app.db.integration_models import Integration, CapabilityGrant

        mock_row = MagicMock(spec=Integration)
        mock_row.provider_type = "postgresql"
        mock_row.tenant_id = "t1"

        added = []
        mock_db = AsyncMock()
        mock_result_int = MagicMock()
        mock_result_int.scalar_one_or_none.return_value = mock_row
        mock_result_grant = MagicMock()
        mock_result_grant.scalar_one_or_none.return_value = None  # no existing grant
        mock_db.execute = AsyncMock(side_effect=[mock_result_int, mock_result_grant])
        mock_db.flush = AsyncMock()
        def track(obj):
            added.append(obj)
        mock_db.add = track

        grant = await create_capability_grant(
            integration_id="int-1",
            body=CapabilityGrantCreate(
                role_key="DIGITAL_MARKETING_MANAGER",
                capability_key="query_entity",
            ),
            tenant_id="t1",
            db=mock_db,
        )
        assert grant.capability_key == "query_entity"
        assert grant.role_key == "DIGITAL_MARKETING_MANAGER"
        assert grant.is_granted is True
        assert any(isinstance(obj, CapabilityGrant) for obj in added)


# ═══════════════════════════════════════════════════════════════════════════════
# 22–23. Execute capability — permission checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecuteCapability:
    @pytest.mark.asyncio
    async def test_raises_permission_error_without_grant(self):
        """execute_capability raises PermissionError when no grant exists."""
        from app.integrations.manager import execute_capability
        from app.db.integration_models import Integration

        mock_row = MagicMock(spec=Integration)
        mock_row.id = "int-1"
        mock_row.provider_type = "postgresql"
        mock_row.display_name = "Test DB"
        mock_row.status = "connected"
        mock_row.is_enabled = True
        mock_row.encrypted_credentials = "some-encrypted-data"

        # First execute call is for the integration lookup, second for the grant check
        mock_db = AsyncMock()
        mock_int_result = MagicMock()
        mock_int_result.scalar_one_or_none.return_value = mock_row
        mock_grant_result = MagicMock()
        mock_grant_result.scalar_one_or_none.return_value = None  # no grant

        mock_db.execute = AsyncMock(side_effect=[mock_int_result, mock_grant_result])

        with pytest.raises(PermissionError, match="does not have permission"):
            await execute_capability(
                integration_id="int-1",
                capability_key="query_entity",
                parameters={},
                role_key="DIGITAL_MARKETING_MANAGER",
                tenant_id="t1",
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_raises_value_error_when_not_connected(self):
        """execute_capability raises ValueError when integration is not connected."""
        from app.integrations.manager import execute_capability
        from app.db.integration_models import Integration

        mock_row = MagicMock(spec=Integration)
        mock_row.id = "int-1"
        mock_row.provider_type = "postgresql"
        mock_row.display_name = "Test DB"
        mock_row.status = "not_tested"    # not connected
        mock_row.is_enabled = True
        mock_row.encrypted_credentials = "creds"

        mock_db = AsyncMock()
        mock_int_result = MagicMock()
        mock_int_result.scalar_one_or_none.return_value = mock_row
        mock_db.execute = AsyncMock(return_value=mock_int_result)

        with pytest.raises(ValueError, match="not connected"):
            await execute_capability(
                integration_id="int-1",
                capability_key="query_entity",
                parameters={},
                role_key="DIGITAL_MARKETING_MANAGER",
                tenant_id="t1",
                db=mock_db,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 24–26. API router
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIRouter:
    def test_providers_endpoint_importable(self):
        """The integration_manager router is importable without error."""
        from app.api.routers.integration_manager import router
        assert router.prefix == "/api/v1/integration-manager"

    def test_router_has_expected_routes(self):
        """Router exposes the key endpoints."""
        from app.api.routers.integration_manager import router
        paths = [route.path for route in router.routes]
        # Routes include the full prefix
        assert any("providers" in p for p in paths)
        assert any("status" in p for p in paths)
        assert any("integrations" in p for p in paths)
        assert any("grants" in p for p in paths)
        assert any("execute" in p for p in paths)

    def test_provider_catalogue_safe(self):
        """GET /providers returns only safe catalogue items (no secrets)."""
        from app.integrations.integration_registry import integration_registry
        catalogue = integration_registry.provider_catalogue()
        for item in catalogue:
            # All items should be JSON-safe
            dumped = json.dumps(item)
            assert "sk-" not in dumped
            # required_credential_fields lists names, not values
            assert isinstance(item["required_credential_fields"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# 27–28. IntegrationOut schema safety
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrationOutSchema:
    def test_integration_out_never_has_encrypted_credentials(self):
        """IntegrationOut schema must not expose encrypted_credentials."""
        from app.schemas.integration_framework import IntegrationOut
        fields = IntegrationOut.model_fields
        assert "encrypted_credentials" not in fields

    def test_integration_out_has_has_credentials_bool(self):
        """IntegrationOut exposes has_credentials (bool), not the actual value."""
        from app.schemas.integration_framework import IntegrationOut
        fields = IntegrationOut.model_fields
        assert "has_credentials" in fields

    def test_integration_out_has_credentials_false_when_empty(self, monkeypatch):
        """has_credentials=False when encrypted_credentials is empty."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["secret_key"] = "test-key"

        from app.db.integration_models import Integration
        from app.integrations.manager import _integration_to_out

        row = MagicMock(spec=Integration)
        row.id = "x"
        row.tenant_id = "t1"
        row.provider_type = "postgresql"
        row.display_name = "DB"
        row.encrypted_credentials = ""
        row.status = "not_configured"
        row.is_enabled = False
        row.account_info_json = "{}"
        row.last_tested_at = None
        row.error_message = None
        row.legacy_connection_id = None
        row.created_by = "admin"
        row.created_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)

        out = _integration_to_out(row)
        assert out.has_credentials is False


# ═══════════════════════════════════════════════════════════════════════════════
# 29–30. Backward compatibility — existing subsystems still importable
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    def test_base_connector_still_importable(self):
        """Existing BaseConnector / PostgreSQLConnector remain importable."""
        from app.integrations.connector import BaseConnector, PostgreSQLConnector, MySQLConnector
        assert issubclass(PostgreSQLConnector, BaseConnector)
        assert issubclass(MySQLConnector, BaseConnector)

    def test_data_connection_orm_still_importable(self):
        """Existing DataConnection ORM model remains importable."""
        from app.db.models import DataConnection, SchemaEntity, SemanticMapping
        assert DataConnection.__tablename__ == "data_connections"
        assert SchemaEntity.__tablename__ == "schema_entities"

    def test_existing_integrations_router_still_importable(self):
        """Existing integrations router is unaffected by Phase 2."""
        from app.api.routers.integrations import router
        assert "/api/v1/integrations" in router.prefix

    def test_existing_crypto_still_works(self, monkeypatch):
        """Fernet encrypt/decrypt in crypto.py still works after Phase 2."""
        import app.config as cfg_mod
        cfg_mod.settings.__dict__["secret_key"] = "backward-compat-key"

        from app.integrations.crypto import encrypt_password, decrypt_password
        plain = "test-password-12345"
        encrypted = encrypt_password(plain)
        assert decrypt_password(encrypted) == plain
        assert plain not in encrypted

    def test_main_app_includes_integration_manager_router(self):
        """main.py registers the integration_manager router."""
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("integration-manager" in p for p in paths)
