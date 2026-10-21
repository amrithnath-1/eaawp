"""
Google OAuth end to end in a CONTROLLED environment.

Real: our FastAPI app, routers, database (temp SQLite), encryption, state
handling, tenant binding, token persistence, refresh persistence, disconnect.
Faked (at the network boundary ONLY): Google's token endpoint
(``Flow.fetch_token``), Google's token refresh (``Credentials.refresh``), the
Search Console API client (``discovery.build``) and Google's revoke endpoint
(``requests.post``).  All "credentials" below are made-up strings; assertions
check they never reach logs, API responses or the database in clear text.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, text

from app.config import settings
from app.db.integration_models import Integration
from app.db.oauth_models import OAuthState

ACCESS = "ya29.FAKE-access-token-0001"
REFRESH = "1//FAKE-refresh-token-0001"
NEW_ACCESS = "ya29.FAKE-access-token-REFRESHED"
CODE = "4/FAKE-auth-code-0001"
CLIENT_SECRET = "FAKE-client-secret-value"
SECRETS = (ACCESS, REFRESH, NEW_ACCESS, CODE, CLIENT_SECRET)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "fake-client-id.apps.example.test")
    monkeypatch.setattr(settings, "google_client_secret", CLIENT_SECRET)
    monkeypatch.setattr(settings, "google_redirect_uri", "http://testserver/api/v1/oauth/google/callback")

    calls = SimpleNamespace(fetch=[], refresh=0, revoked=[], api=0)

    import google_auth_oauthlib.flow as flow_mod

    def fake_fetch_token(self, **kw):
        calls.fetch.append(kw.get("code"))
        if kw.get("code") == "BOOM":
            raise RuntimeError(f"invalid_grant: bad code, client_secret={CLIENT_SECRET} refresh_token={REFRESH}")
        self.oauth2session.token = {
            "access_token": ACCESS, "refresh_token": REFRESH, "token_type": "Bearer",
            "expires_at": time.time() - 600,   # already expired -> forces a refresh later
            "scope": ["https://www.googleapis.com/auth/webmasters.readonly"],
        }

    monkeypatch.setattr(flow_mod.Flow, "fetch_token", fake_fetch_token)

    import google.oauth2.credentials as gcreds

    def fake_refresh(self, request):
        calls.refresh += 1
        assert self.refresh_token == REFRESH, "refresh must use the stored (decrypted) refresh token"
        self.token = NEW_ACCESS
        self.expiry = datetime.utcnow() + timedelta(hours=1)

    monkeypatch.setattr(gcreds.Credentials, "refresh", fake_refresh)

    import app.integrations.providers.google_search_console_provider as gsc

    class _Req:
        def __init__(self, payload): self.payload = payload
        def execute(self): calls.api += 1; return self.payload

    fake_service = SimpleNamespace(sites=lambda: SimpleNamespace(
        list=lambda **kw: _Req({"siteEntry": [{"siteUrl": "https://example.test/", "permissionLevel": "siteOwner"}]})))
    monkeypatch.setattr(gsc.discovery, "build", lambda *a, **k: fake_service)

    async def ok_test(self, credentials):
        from app.integrations.provider import ConnectionTestResult
        return ConnectionTestResult(success=True, account_info={"sites": 1}, error_message=None)

    monkeypatch.setattr(gsc.GoogleSearchConsoleProvider, "test_connection", ok_test)

    import requests

    def fake_post(url, params=None, **kw):
        calls.revoked.append((url, (params or {}).get("token")))
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(requests, "post", fake_post)
    return calls


def _our_logs(caplog) -> str:
    """Log lines from OUR code (the test HTTP client logs the request URL itself)."""
    return "\n".join(r.getMessage() for r in caplog.records
                     if r.name.startswith(("app", "eaawp")))


def _authorize(world, who="a_admin", path="/api/v1/oauth/google/authorize"):
    r = world.client.get(path, headers=world.auth(who))
    assert r.status_code == 200, r.text
    return r.json()


def _row(world, integration_id):
    async def go():
        async with world.maker() as s:
            return (await s.execute(select(Integration).where(Integration.id == integration_id))).scalar_one_or_none()
    return run(go())


def _state(world, token):
    async def go():
        async with world.maker() as s:
            return (await s.execute(select(OAuthState).where(OAuthState.state_token == token))).scalar_one_or_none()
    return run(go())


def _callback(world, state, code=CODE):
    return world.client.get(f"/api/v1/oauth/google/callback?code={code}&state={state}", follow_redirects=False)


def _connect(world, who="a_admin"):
    auth = _authorize(world, who)
    state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
    r = _callback(world, state)
    assert r.status_code == 302 and "success=true" in r.headers["location"], r.headers.get("location")
    return auth["integration_id"], state


class TestAuthorize:
    def test_authorization_url_is_correct_and_carries_no_secret(self, world, google):
        auth = _authorize(world)
        q = parse_qs(urlparse(auth["authorization_url"]).query)
        assert urlparse(auth["authorization_url"]).netloc == "accounts.google.com"
        assert q["client_id"] == ["fake-client-id.apps.example.test"]
        assert q["redirect_uri"] == ["http://testserver/api/v1/oauth/google/callback"]
        assert q["access_type"] == ["offline"]
        assert q["scope"] == ["https://www.googleapis.com/auth/webmasters.readonly"]
        assert q["state"] == [auth["state_token"]]
        assert CLIENT_SECRET not in auth["authorization_url"] and "client_secret" not in q

    def test_state_is_random_and_unique(self, world, google):
        tokens = {_authorize(world)["state_token"] for _ in range(3)}
        assert len(tokens) == 3 and all(len(t) == 64 for t in tokens)

    def test_employee_cannot_start_a_connection(self, world, google):
        for p in ("/api/v1/oauth/google/authorize", "/api/v1/oauth/google/analytics/authorize"):
            assert world.client.get(p, headers=world.auth("a_employee")).status_code == 403

    def test_state_row_is_bound_to_tenant_user_and_integration(self, world, google):
        auth = _authorize(world)
        st = _state(world, auth["state_token"])
        assert (st.tenant_id, st.initiated_by_user_id, st.integration_id, st.used) == (
            world.tenant_a, world.users["a_admin"]["id"], auth["integration_id"], False)


class TestCallbackAndStorage:
    def test_happy_path_stores_encrypted_tokens_for_the_right_tenant(self, world, google):
        integration_id, state = _connect(world)
        assert google.fetch == [CODE]

        row = _row(world, integration_id)
        assert row.tenant_id == world.tenant_a and row.provider_type == "google_search_console"
        assert row.is_enabled and row.status == "connected"

        # encrypted at rest: no secret appears in the stored blob or anywhere in the DB file
        blob = row.encrypted_credentials
        assert blob and not any(s in blob for s in SECRETS)
        raw = run(self._dump(world))
        assert not any(s in raw for s in (ACCESS, REFRESH, CODE)), "token stored in clear text"

        # ...but decrypts (with the server key) to exactly what Google issued
        from app.integrations.manager import _decrypt_credentials
        creds = _decrypt_credentials(blob)
        assert creds["access_token"] == ACCESS and creds["refresh_token"] == REFRESH

        # tampering with the ciphertext is detected
        from cryptography.fernet import InvalidToken
        with pytest.raises(InvalidToken):
            _decrypt_credentials(blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB"))

        assert _state(world, state).used is True

    @staticmethod
    async def _dump(world):
        # every text column of every table, concatenated
        out = []
        async with world.maker() as s:
            tables = [r[0] for r in (await s.execute(text("select name from sqlite_master where type='table'"))).all()]
            for t in tables:
                for row in (await s.execute(text(f'select * from "{t}"'))).all():
                    out.append(" ".join(str(v) for v in row))
        return "\n".join(out)

    def test_api_never_returns_credentials(self, world, google):
        integration_id, _ = _connect(world)
        for path in (f"/api/v1/integration-manager/integrations/{integration_id}",
                     "/api/v1/integration-manager/integrations"):
            r = world.client.get(path, headers=world.auth("a_admin"))
            assert r.status_code == 200
            assert not any(s in r.text for s in SECRETS)
            assert "has_credentials" in r.text

    def test_state_is_single_use(self, world, google):
        integration_id, state = _connect(world)
        before = _row(world, integration_id).encrypted_credentials
        r = _callback(world, state, code="SECOND-CODE")
        assert r.status_code == 302 and "error=invalid_state" in r.headers["location"]
        assert google.fetch == [CODE], "replayed state must not trigger a second token exchange"
        assert _row(world, integration_id).encrypted_credentials == before

    def test_state_bound_to_tenant_a_cannot_write_into_tenant_b(self, world, google):
        """Callback uses the TENANT STORED IN THE STATE, never anything the caller sends."""
        auth = _authorize(world, "a_admin")
        state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
        r = world.client.get(f"/api/v1/oauth/google/callback?code={CODE}&state={state}&tenant_id={world.tenant_b}",
                             headers={"X-Tenant-ID": world.tenant_b, **world.auth("b_admin")}, follow_redirects=False)
        assert r.status_code == 302 and "success=true" in r.headers["location"]
        assert _row(world, auth["integration_id"]).tenant_id == world.tenant_a
        # tenant B sees nothing of it
        lst = world.client.get("/api/v1/integration-manager/integrations", headers=world.auth("b_admin"))
        assert lst.status_code == 200 and lst.json() == []

    def test_other_tenant_cannot_use_or_delete_the_connection(self, world, google):
        integration_id, _ = _connect(world)
        base = f"/api/v1/integration-manager/integrations/{integration_id}"
        h = world.auth("b_admin")
        assert world.client.get(base, headers=h).status_code == 404
        assert world.client.post(base + "/test", headers=h).status_code == 404
        assert world.client.patch(base, headers=h, json={"is_enabled": False}).status_code == 404
        assert world.client.delete(base, headers=h).status_code == 404
        assert world.client.post(base + "/execute", headers=h, json={
            "capability_key": "list_sites", "role_key": "DIGITAL_MARKETING_MANAGER", "parameters": {}}).status_code == 404
        assert _row(world, integration_id) is not None and google.revoked == []

    def test_legacy_state_without_initiating_user_is_refused_and_burned(self, world, google):
        """States created before the migration (NULL initiator) must not complete a connection."""
        auth = _authorize(world)

        async def legacy():
            async with world.maker() as s:
                st = (await s.execute(select(OAuthState).where(OAuthState.state_token == auth["state_token"]))).scalar_one()
                st.initiated_by_user_id = None
                await s.commit()
        run(legacy())
        r = _callback(world, auth["state_token"])
        assert "error=invalid_state" in r.headers["location"] and google.fetch == []
        assert _state(world, auth["state_token"]).used is True

    def test_expired_state_is_rejected(self, world, google):
        auth = _authorize(world)

        async def expire():
            async with world.maker() as s:
                st = (await s.execute(select(OAuthState).where(OAuthState.state_token == auth["state_token"]))).scalar_one()
                st.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                await s.commit()
        run(expire())
        r = _callback(world, auth["state_token"])
        assert "error=expired_state" in r.headers["location"] and google.fetch == []

    def test_unknown_missing_and_google_error_never_exchange(self, world, google):
        for qs in ("code=x&state=" + "0" * 64, f"code={CODE}", "state=abc", "error=access_denied"):
            r = world.client.get(f"/api/v1/oauth/google/callback?{qs}", follow_redirects=False)
            assert r.status_code == 302 and "error=" in r.headers["location"], qs
        assert google.fetch == []

    def test_failed_exchange_redirects_with_generic_error_and_leaks_nothing(self, world, google, caplog):
        auth = _authorize(world)
        caplog.set_level(logging.DEBUG)
        r = _callback(world, auth["state_token"], code="BOOM")
        assert "error=token_exchange_failed" in r.headers["location"]
        assert not any(s in r.headers["location"] + r.text for s in SECRETS)
        assert not any(s in _our_logs(caplog) for s in SECRETS), "secret leaked into logs on failed exchange"
        assert _row(world, auth["integration_id"]).encrypted_credentials is not None
        creds_blob = _row(world, auth["integration_id"]).encrypted_credentials
        from app.integrations.manager import _decrypt_credentials
        assert _decrypt_credentials(creds_blob) == {}, "failed exchange must not store partial tokens"

    def test_no_secret_is_logged_on_the_happy_path(self, world, google, caplog):
        caplog.set_level(logging.DEBUG)
        _connect(world)
        ours = _our_logs(caplog)
        assert ours, "expected application log lines"
        assert not any(s in ours for s in SECRETS), "secret leaked into application logs"

    def test_concurrent_callbacks_exchange_the_code_only_once(self, world, google):
        """Two browsers hitting the callback with the same state: exactly one wins."""
        import threading
        auth = _authorize(world)
        results = []

        def hit():
            results.append(_callback(world, auth["state_token"]).headers["location"])

        ts = [threading.Thread(target=hit) for _ in range(4)]
        [t.start() for t in ts]; [t.join() for t in ts]
        assert sum("success=true" in loc for loc in results) == 1, results
        assert len(google.fetch) == 1


class TestRefreshAndDisconnect:
    def _grant(self, world, integration_id):
        r = world.client.post(f"/api/v1/integration-manager/integrations/{integration_id}/grants",
                              headers=world.auth("a_admin"),
                              json={"grants": [{"role_key": "DIGITAL_MARKETING_MANAGER", "capability_key": "list_sites"}]})
        assert r.status_code == 201, r.text

    def _execute(self, world, integration_id, who="a_admin"):
        return world.client.post(f"/api/v1/integration-manager/integrations/{integration_id}/execute",
                                 headers=world.auth(who),
                                 json={"capability_key": "list_sites", "role_key": "DIGITAL_MARKETING_MANAGER", "parameters": {}})

    def test_expired_access_token_is_refreshed_and_the_new_token_persisted_encrypted(self, world, google):
        integration_id, _ = _connect(world)
        self._grant(world, integration_id)

        r = self._execute(world, integration_id)
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True and r.json()["row_count"] == 1
        assert google.refresh == 1 and google.api == 1
        assert not any(s in r.text for s in SECRETS)

        row = _row(world, integration_id)
        assert NEW_ACCESS not in row.encrypted_credentials
        from app.integrations.manager import _decrypt_credentials
        creds = _decrypt_credentials(row.encrypted_credentials)
        assert creds["access_token"] == NEW_ACCESS and creds["refresh_token"] == REFRESH

        # next call reuses the fresh token: no second refresh
        assert self._execute(world, integration_id).status_code == 200
        assert google.refresh == 1

    def test_capability_requires_admin_and_an_explicit_grant(self, world, google):
        integration_id, _ = _connect(world)
        assert self._execute(world, integration_id, "a_employee").status_code == 403
        r = self._execute(world, integration_id)          # no grant yet
        assert r.status_code == 403 and google.api == 0

    @staticmethod
    async def _grant_count(world, integration_id):
        from app.db.integration_models import CapabilityGrant
        async with world.maker() as s:
            return len((await s.execute(select(CapabilityGrant).where(
                CapabilityGrant.integration_id == integration_id))).scalars().all())

    def test_disconnect_revokes_at_google_and_destroys_local_credentials(self, world, google):
        integration_id, _ = _connect(world)
        self._grant(world, integration_id)

        assert world.client.delete(f"/api/v1/integration-manager/integrations/{integration_id}",
                                   headers=world.auth("a_employee")).status_code == 403
        assert _row(world, integration_id) is not None

        r = world.client.delete(f"/api/v1/integration-manager/integrations/{integration_id}", headers=world.auth("a_admin"))
        assert r.status_code in (200, 204), r.text
        assert google.revoked == [("https://oauth2.googleapis.com/revoke", REFRESH)]
        assert _row(world, integration_id) is None
        raw = run(TestCallbackAndStorage._dump(world))
        assert not any(s in raw for s in (ACCESS, REFRESH, NEW_ACCESS))
        assert run(self._grant_count(world, integration_id)) == 0, "grants must be removed with the integration"
        assert self._execute(world, integration_id).status_code == 404

    def test_disconnect_still_deletes_locally_when_google_is_unreachable(self, world, google, monkeypatch):
        import requests
        integration_id, _ = _connect(world)

        def down(*a, **k):
            raise requests.ConnectionError(f"offline refresh_token={REFRESH}")
        monkeypatch.setattr(requests, "post", down)
        r = world.client.delete(f"/api/v1/integration-manager/integrations/{integration_id}", headers=world.auth("a_admin"))
        assert r.status_code in (200, 204)
        assert _row(world, integration_id) is None

    def test_dedicated_encryption_key_can_still_read_old_data(self, world, google, monkeypatch):
        integration_id, _ = _connect(world)
        blob = _row(world, integration_id).encrypted_credentials          # written under SECRET_KEY
        monkeypatch.setattr(settings, "encryption_key", "a-different-dedicated-encryption-key-123")
        from app.integrations.manager import _decrypt_credentials, _encrypt_credentials
        assert _decrypt_credentials(blob)["refresh_token"] == REFRESH     # old data still readable
        new_blob = _encrypt_credentials({"x": "y"})
        monkeypatch.setattr(settings, "encryption_key", "")               # new key gone -> new data unreadable
        from cryptography.fernet import InvalidToken
        with pytest.raises(InvalidToken):
            _decrypt_credentials(new_blob)
