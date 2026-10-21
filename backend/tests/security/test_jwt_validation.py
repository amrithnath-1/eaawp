"""JWT / session validation beyond the basics covered in test_tenant_isolation."""
from __future__ import annotations

import asyncio
import time

import pytest
from jose import jwt
from sqlalchemy import update

from app.config import settings
from tests.conftest import PASSWORD
from tests.security.helpers import TEST_SECRET, forge_token

ME = "/api/v1/auth/me"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _login(world, who="a_admin"):
    u = world.users[who]
    r = world.client.post("/api/v1/auth/token", json={
        "email": u["email"], "password": PASSWORD, "company_id": u["tenant_id"]})
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(t):
    return {"Authorization": f"Bearer {t}"}


class TestIssuerAudience:
    def test_not_enforced_when_not_configured(self, world):
        assert world.client.get(ME, headers=world.auth("a_admin")).status_code == 200

    def test_configured_values_are_written_and_required(self, world, monkeypatch):
        monkeypatch.setattr(settings, "jwt_issuer", "https://api.eaawp.example")
        monkeypatch.setattr(settings, "jwt_audience", "eaawp-web")
        good = _login(world)["access_token"]
        claims = jwt.get_unverified_claims(good)
        assert claims["iss"] == "https://api.eaawp.example" and claims["aud"] == "eaawp-web"
        assert world.client.get(ME, headers=_bearer(good)).status_code == 200

        u = world.users["a_admin"]
        base = {"sub": u["id"], "tid": u["tenant_id"]}
        for label, token in {
            "no iss/aud": forge_token(base),
            "wrong iss": forge_token({**base, "iss": "https://evil.example", "aud": "eaawp-web"}),
            "wrong aud": forge_token({**base, "iss": "https://api.eaawp.example", "aud": "other-app"}),
            "no aud": forge_token({**base, "iss": "https://api.eaawp.example"}),
            "no iss": forge_token({**base, "aud": "eaawp-web"}),
        }.items():
            assert world.client.get(ME, headers=_bearer(token)).status_code == 401, label

    def test_tokens_issued_before_enabling_are_rejected_after(self, world, monkeypatch):
        old = _login(world)["access_token"]
        monkeypatch.setattr(settings, "jwt_audience", "eaawp-web")
        assert world.client.get(ME, headers=_bearer(old)).status_code == 401


class TestClaimsAndTimes:
    def test_not_yet_valid_token_is_rejected(self, world):
        u = world.users["a_admin"]
        t = forge_token({"sub": u["id"], "nbf": int(time.time()) + 3600})
        assert world.client.get(ME, headers=_bearer(t)).status_code == 401

    def test_wrong_signing_algorithm_is_rejected(self, world):
        u = world.users["a_admin"]
        t = forge_token({"sub": u["id"]}, algorithm="HS512")
        assert world.client.get(ME, headers=_bearer(t)).status_code == 401

    def test_identity_comes_from_the_database_not_the_token(self, world):
        u = world.users["a_employee"]
        t = forge_token({"sub": u["id"], "tid": world.tenant_b, "role": "superadmin", "email": "x@evil.test"})
        r = world.client.get(ME, headers=_bearer(t))
        assert r.status_code == 200
        body = r.json()
        assert body["tenant_id"] == world.tenant_a and body["role"] == "Employee"
        assert body["email"] == u["email"]

    def test_deactivated_user_is_locked_out_immediately(self, world):
        from app.db.models import User
        h = world.auth("a_employee")
        assert world.client.get(ME, headers=h).status_code == 200

        async def off():
            async with world.maker() as s:
                await s.execute(update(User).where(User.id == world.users["a_employee"]["id"]).values(is_active=False))
                await s.commit()
        run(off())
        assert world.client.get(ME, headers=h).status_code == 401


class TestRefreshTokens:
    def test_rotation_old_token_cannot_be_replayed(self, world):
        tokens = _login(world)
        r1 = world.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r1.status_code == 200
        r2 = world.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r2.status_code == 401
        assert world.client.post("/api/v1/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code == 200

    def test_access_token_is_not_a_refresh_token(self, world):
        tokens = _login(world)
        assert world.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401

    def test_refresh_token_is_not_an_access_token(self, world):
        tokens = _login(world)
        assert world.client.get(ME, headers=_bearer(tokens["refresh_token"])).status_code == 401

    def test_logout_revokes(self, world):
        tokens = _login(world)
        assert world.client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
        assert world.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401

    def test_logout_all_revokes_every_session(self, world):
        a, b = _login(world), _login(world)
        assert world.client.post("/api/v1/auth/logout/all", headers=_bearer(a["access_token"])).status_code == 204
        for t in (a, b):
            assert world.client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401

    def test_deactivated_user_cannot_refresh(self, world):
        from app.db.models import User
        tokens = _login(world, "a_employee")

        async def off():
            async with world.maker() as s:
                await s.execute(update(User).where(User.id == world.users["a_employee"]["id"]).values(is_active=False))
                await s.commit()
        run(off())
        assert world.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401

    def test_signed_subject_must_match_the_stored_record(self, world):
        """A refresh JWT that reuses a real jti but names ANOTHER user is refused."""
        tokens = _login(world, "a_employee")
        real = jwt.get_unverified_claims(tokens["refresh_token"])
        forged = jwt.encode({**real, "sub": world.users["b_admin"]["id"], "tid": world.tenant_b},
                            TEST_SECRET, algorithm="HS256")
        r = world.client.post("/api/v1/auth/refresh", json={"refresh_token": forged})
        assert r.status_code == 401

    def test_refresh_returns_tenant_and_role_from_the_database(self, world):
        tokens = _login(world, "a_employee")
        out = world.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()
        assert out["tenant_id"] == world.tenant_a and out["role"] == "Employee"

    def test_stored_refresh_tokens_are_hashed(self, world):
        from sqlalchemy import select
        from app.db.models import RefreshToken
        tokens = _login(world)

        async def rows():
            async with world.maker() as s:
                return [r.token_hash for r in (await s.execute(select(RefreshToken))).scalars().all()]
        hashes = run(rows())
        assert hashes and tokens["refresh_token"] not in hashes
        assert all(len(h) == 64 for h in hashes)


class TestStartupGuards:
    def _boot(self):
        from app.main import app, lifespan

        async def go():
            async with lifespan(app):
                pass
        run(go())

    @pytest.mark.parametrize("secret", [
        "changeme", "short", "", "dev-insecure-key-replace-in-production",
        "changeme-generate-a-real-secret-key",            # the old .env.example value
        "CHANGEME" + "x" * 40, "a-long-enough-key-but-Replace-Me-1234567890", "x" * 64,
    ])
    def test_weak_secret_refuses_to_start(self, monkeypatch, secret):
        monkeypatch.setattr(settings, "secret_key", secret)
        with pytest.raises(RuntimeError, match="STARTUP REFUSED"):
            self._boot()

    @pytest.mark.parametrize("alg", ["none", "RS256", "HS1"])
    def test_non_hmac_algorithm_refuses_to_start(self, monkeypatch, alg):
        monkeypatch.setattr(settings, "secret_key", TEST_SECRET)
        monkeypatch.setattr(settings, "algorithm", alg)
        with pytest.raises(RuntimeError, match="ALGORITHM"):
            self._boot()

    def test_wildcard_cors_refuses_to_start_in_production(self, monkeypatch):
        monkeypatch.setattr(settings, "secret_key", TEST_SECRET)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "cors_origins", "*")
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            self._boot()


class TestSecretKeyPolicy:
    from app.core.startup_checks import secret_key_problem

    def test_generated_secrets_are_accepted(self):
        import secrets
        from app.core.startup_checks import secret_key_problem
        for _ in range(200):
            assert secret_key_problem(secrets.token_hex(32)) is None
            assert secret_key_problem(secrets.token_urlsafe(48)) is None

    def test_env_example_ships_no_usable_secret(self):
        import pathlib, re
        from app.core.startup_checks import secret_key_problem
        text = (pathlib.Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
        m = re.search(r"^SECRET_KEY=(.*)$", text, re.M)
        assert m, "SECRET_KEY line missing from .env.example"
        value = m.group(1).strip().strip('"').strip("'")
        assert value == "", "the example file must not contain a SECRET_KEY value"
        assert secret_key_problem(value) is not None

    def test_empty_secret_refuses_to_start_in_production(self, monkeypatch):
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "secret_key", "")
        monkeypatch.setattr(settings, "cors_origins", "https://app.example.com")
        with pytest.raises(RuntimeError, match="STARTUP REFUSED"):
            TestStartupGuards()._boot()
