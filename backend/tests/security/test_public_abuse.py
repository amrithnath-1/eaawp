"""Abuse protection for the intentionally public endpoints."""
from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.core.rate_limit import limiter
from tests.conftest import PASSWORD


def _company(i: int | str = 0, **over):
    body = {
        "company_name": f"Acme {i}-{uuid.uuid4().hex[:6]}",
        "admin_name": "Ada Admin",
        "admin_email": f"ada{uuid.uuid4().hex[:6]}@example.test",
        "admin_password": "Sup3r-secret-pw",
    }
    body.update(over)
    return body


@pytest.fixture()
def tight(monkeypatch):
    monkeypatch.setattr(settings, "registration_rate_limit", 3)
    monkeypatch.setattr(settings, "registration_rate_window_seconds", 3600)


class TestRegistrationAbuse:
    def test_sixth_registration_from_one_ip_is_429_with_retry_after(self, world, tight):
        c = world.client
        codes = [c.post("/api/v1/onboarding/company", json=_company(i)).status_code for i in range(3)]
        assert codes == [201, 201, 201]
        r = c.post("/api/v1/onboarding/company", json=_company("x"))
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1

    def test_invalid_payloads_also_consume_the_budget(self, world, tight):
        c = world.client
        for _ in range(3):
            assert c.post("/api/v1/onboarding/company", json={}).status_code == 422
        assert c.post("/api/v1/onboarding/company", json=_company("y")).status_code == 429

    def test_global_daily_cap(self, world, monkeypatch):
        monkeypatch.setattr(settings, "registration_daily_cap", 2)
        c = world.client
        assert c.post("/api/v1/onboarding/company", json=_company(1)).status_code == 201
        assert c.post("/api/v1/onboarding/company", json=_company(2)).status_code == 201
        assert c.post("/api/v1/onboarding/company", json=_company(3)).status_code == 429

    def test_registration_can_be_closed(self, world, monkeypatch):
        monkeypatch.setattr(settings, "registration_enabled", False)
        r = world.client.post("/api/v1/onboarding/company", json=_company(1))
        assert r.status_code == 403

    def test_overlong_password_is_422_not_500(self, world):
        r = world.client.post("/api/v1/onboarding/company", json=_company(1, admin_password="a" * 73))
        assert r.status_code == 422

    def test_spoofed_forwarded_for_does_not_reset_the_limit(self, world, tight):
        c = world.client
        for i in range(3):
            assert c.post("/api/v1/onboarding/company", json=_company(i),
                          headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code == 201
        r = c.post("/api/v1/onboarding/company", json=_company("z"), headers={"X-Forwarded-For": "198.51.100.9"})
        assert r.status_code == 429

    def test_forwarded_for_is_honoured_only_behind_a_trusted_proxy(self, world, tight, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxy_count", 1)
        c = world.client
        for i in range(3):
            assert c.post("/api/v1/onboarding/company", json=_company(i),
                          headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 201
        # different real client (as seen by our one trusted proxy) => separate budget
        assert c.post("/api/v1/onboarding/company", json=_company("o"),
                      headers={"X-Forwarded-For": "203.0.113.8"}).status_code == 201
        assert c.post("/api/v1/onboarding/company", json=_company("p"),
                      headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 429

    def test_limiter_can_be_switched_off(self, world, tight, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        for i in range(5):
            assert world.client.post("/api/v1/onboarding/company", json=_company(i)).status_code == 201


class TestLoginBruteForce:
    def _login(self, world, who, password):
        u = world.users[who]
        return world.client.post("/api/v1/auth/token", json={
            "email": u["email"], "password": password, "company_id": u["tenant_id"]})

    def test_lockout_after_repeated_failures_even_for_the_right_password(self, world):
        for _ in range(settings.login_max_failures):
            assert self._login(world, "a_admin", "wrong").status_code == 401
        r = self._login(world, "a_admin", PASSWORD)
        assert r.status_code == 429
        assert "Retry-After" in r.headers

    def test_lockout_is_per_account(self, world):
        for _ in range(settings.login_max_failures):
            self._login(world, "a_admin", "wrong")
        assert self._login(world, "b_admin", PASSWORD).status_code == 200

    def test_success_resets_the_failure_counter(self, world):
        for _ in range(settings.login_max_failures - 1):
            self._login(world, "a_admin", "wrong")
        assert self._login(world, "a_admin", PASSWORD).status_code == 200
        for _ in range(settings.login_max_failures - 1):
            self._login(world, "a_admin", "wrong")
        assert self._login(world, "a_admin", PASSWORD).status_code == 200

    def test_per_ip_login_ceiling(self, world, monkeypatch):
        monkeypatch.setattr(settings, "login_rate_limit", 4)
        codes = [self._login(world, "a_admin", "wrong").status_code for _ in range(5)]
        assert codes[:4] == [401] * 4 and codes[4] == 429

    def test_unknown_account_is_throttled_too(self, world):
        for _ in range(settings.login_max_failures):
            r = world.client.post("/api/v1/auth/token", json={
                "email": "nobody@example.test", "password": "x", "company_id": world.tenant_a})
            assert r.status_code == 401
        r = world.client.post("/api/v1/auth/token", json={
            "email": "nobody@example.test", "password": "x", "company_id": world.tenant_a})
        assert r.status_code == 429

    def test_refresh_is_rate_limited(self, world, monkeypatch):
        monkeypatch.setattr(settings, "refresh_rate_limit", 3)
        codes = [world.client.post("/api/v1/auth/refresh", json={"refresh_token": "junk"}).status_code
                 for _ in range(4)]
        assert codes == [401, 401, 401, 429]


class TestOAuthCallbackThrottle:
    def test_callback_is_rate_limited(self, world, monkeypatch):
        monkeypatch.setattr(settings, "google_client_id", "test-client-id")
        monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
        monkeypatch.setattr(settings, "oauth_callback_rate_limit", 3)
        codes = [world.client.get("/api/v1/oauth/google/callback?code=x&state=nope",
                                  follow_redirects=False).status_code for _ in range(4)]
        assert codes == [302, 302, 302, 429]


def test_limiter_memory_is_bounded(monkeypatch):
    import app.core.rate_limit as rl
    monkeypatch.setattr(rl, "_MAX_KEYS", 50)
    lim = rl.SlidingWindowLimiter()
    for i in range(500):
        lim.check(f"k{i}", 5, 3600)
    assert len(lim._events) <= 50
