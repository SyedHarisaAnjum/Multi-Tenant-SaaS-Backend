"""Phase 14: Redis rate limits on abuse-prone endpoints, per IP / account / user / org."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.rate_limit import RateLimiter, RateLimitRule, get_rate_limiter
from app.core.redis import get_redis
from app.main import app
from tests.conftest import Tenants
from tests.helpers import PASSWORD, accept, create_actor, invite, register


@pytest.fixture
def limited(client: TestClient) -> TestClient:
    """The shared client, with real (Redis-backed) rate limiting switched back on.

    Request it *after* data-building fixtures like `tenants`, so their setup
    traffic isn't counted against the limits under test.
    """
    app.dependency_overrides[get_rate_limiter] = lambda: RateLimiter(get_redis())
    return client


def _client_from(ip: str) -> TestClient:
    return TestClient(app, client=(ip, 50000))


def _login(client: TestClient, email: str, password: str = "wrong-password") -> int:
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    ).status_code


def test_login_limited_per_account(limited: TestClient) -> None:
    register(limited, email="victim@example.com")
    statuses = [_login(limited, "victim@example.com") for _ in range(10)]
    assert statuses == [401] * 10

    blocked = limited.post(
        "/api/v1/auth/login", json={"email": "victim@example.com", "password": PASSWORD}
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert 0 < int(blocked.headers["retry-after"]) <= 15 * 60
    # Even the correct password is refused until the window resets: no oracle for guesses.

    register(limited, email="bystander@example.com")
    assert _login(limited, "bystander@example.com", PASSWORD) == 200  # other accounts unaffected


def test_account_limit_holds_across_ips(db: Session, limited: TestClient) -> None:
    register(limited, email="victim@example.com")
    for i in range(10):
        assert _login(_client_from(f"203.0.113.{i}"), "victim@example.com") == 401
    # A botnet can't spread guesses across addresses to dodge the account limit.
    assert _login(_client_from("203.0.113.99"), "victim@example.com") == 429


def test_login_limited_per_ip(limited: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limit, "LOGIN_PER_IP", RateLimitRule("login:ip", 3, 300))
    attacker = _client_from("198.51.100.7")
    # Spraying many accounts from one address.
    assert [_login(attacker, f"user{i}@example.com") for i in range(3)] == [401] * 3
    assert _login(attacker, "user4@example.com") == 429
    assert _login(_client_from("198.51.100.8"), "user4@example.com") == 401  # other IP fine


def test_spoofed_forwarded_for_does_not_bypass_ip_limit(
    limited: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limit, "REGISTER_PER_IP", RateLimitRule("register:ip", 2, 3600))
    statuses = [
        limited.post(
            "/api/v1/auth/register",
            json={"email": f"bot{i}@example.com", "password": PASSWORD},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},  # ignored: not from a trusted proxy
        ).status_code
        for i in range(3)
    ]
    assert statuses == [201, 201, 429]


def test_registration_limited_per_ip(limited: TestClient) -> None:
    statuses = [register(limited, email=f"new{i}@example.com").status_code for i in range(11)]
    assert statuses == [201] * 10 + [429]


def test_invitation_creation_limited_per_user(
    tenants: Tenants, limited: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limit, "INVITE_PER_USER", RateLimitRule("invite:user", 2, 3600))
    codes = [
        invite(limited, tenants.admin, tenants.acme, f"x{i}@example.com").status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 429]
    # Per-user: a different admin of the same org is not blocked.
    assert invite(limited, tenants.owner, tenants.acme, "y@example.com").status_code == 201


def test_invitation_creation_limited_per_org(
    tenants: Tenants, limited: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limit, "INVITE_PER_ORG", RateLimitRule("invite:org", 2, 86400))
    assert invite(limited, tenants.owner, tenants.acme, "a@example.com").status_code == 201
    assert invite(limited, tenants.admin, tenants.acme, "b@example.com").status_code == 201
    assert invite(limited, tenants.owner, tenants.acme, "c@example.com").status_code == 429
    assert invite(limited, tenants.mallory, tenants.globex, "d@example.com").status_code == 201


def test_invitation_accept_limited_per_user(
    tenants: Tenants, limited: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        rate_limit, "INVITE_ACCEPT_PER_USER", RateLimitRule("invite_accept:user", 2, 900)
    )
    guesser = create_actor(limited, "guesser@example.com")
    assert [accept(limited, guesser, f"guess-{i}").status_code for i in range(3)] == [404, 404, 429]


def test_redis_down_fails_open_by_default(limited: TestClient) -> None:
    dead = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1)
    app.dependency_overrides[get_rate_limiter] = lambda: RateLimiter(dead)
    assert register(limited, email="still-works@example.com").status_code == 201


def test_redis_down_can_fail_closed(limited: TestClient) -> None:
    dead = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1)
    app.dependency_overrides[get_rate_limiter] = lambda: RateLimiter(dead, fail_open=False)
    assert register(limited, email="blocked@example.com").status_code == 429


def test_counters_expire_and_do_not_store_identifiers(limited: TestClient) -> None:
    register(limited, email="private@example.com")
    _login(limited, "private@example.com")
    redis = get_redis()
    keys = list(redis.scan_iter("rl:*"))
    assert keys
    assert not any("private@example.com" in k or "testclient" in k for k in keys)
    assert all(redis.ttl(k) > 0 for k in keys)


@pytest.fixture(autouse=True)
def _close_extra_clients() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_rate_limiter, None)
