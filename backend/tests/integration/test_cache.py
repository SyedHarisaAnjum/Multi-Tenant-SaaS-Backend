"""Phase 13: read-through caching with post-commit invalidation and Redis fallback."""

import pytest
from fastapi.testclient import TestClient
from redis import Redis

from app.core import cache
from app.core.cache import Cache
from tests.conftest import Board, Tenants
from tests.helpers import create_project, create_task, create_workspace


def _get(client: TestClient, path: str, actor: object) -> tuple[str, dict]:  # type: ignore[type-arg]
    response = client.get(path, headers=actor.headers)  # type: ignore[attr-defined]
    assert response.status_code == 200, response.text
    return response.headers["x-cache"], response.json()


def test_workspace_list_is_cached_and_invalidated_on_write(
    client: TestClient, tenants: Tenants
) -> None:
    path = f"/api/v1/organizations/{tenants.acme}/workspaces"
    create_workspace(client, tenants.owner, tenants.acme, "one")

    assert _get(client, path, tenants.member)[0] == "MISS"
    hit, body = _get(client, path, tenants.viewer)  # same tenant-wide page for every member
    assert hit == "HIT" and body["total"] == 1

    create_workspace(client, tenants.owner, tenants.acme, "two")  # commit → invalidate
    state, body = _get(client, path, tenants.member)
    assert state == "MISS" and body["total"] == 2


def test_project_list_cache_keys_include_query(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    base = f"/api/v1/organizations/{tenants.acme}/projects"
    _get(client, f"{base}?page=1&page_size=10", tenants.member)
    assert _get(client, f"{base}?page=1&page_size=10", tenants.member)[0] == "HIT"
    # Different page / filter → different entry.
    assert _get(client, f"{base}?page=2&page_size=10", tenants.member)[0] == "MISS"
    assert _get(client, f"{base}?page=1&page_size=10&q=lau", tenants.member)[0] == "MISS"


def test_project_update_invalidates_list(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    path = f"/api/v1/organizations/{tenants.acme}/projects"
    _get(client, path, tenants.member)
    client.patch(
        f"/api/v1/projects/{acme_board.project_id}",
        json={"version": 1, "name": "Renamed"},
        headers=tenants.member.headers,
    )
    state, body = _get(client, path, tenants.member)
    assert state == "MISS"
    assert body["items"][0]["name"] == "Renamed"


def test_summary_is_cached_and_task_writes_invalidate_it(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    path = f"/api/v1/organizations/{tenants.acme}/summary"
    state, summary = _get(client, path, tenants.viewer)
    assert state == "MISS"
    assert summary["members"] == 4 and summary["projects"]["total"] == 1
    assert _get(client, path, tenants.viewer)[0] == "HIT"

    create_task(client, tenants.member, acme_board.project_id, "New")
    state, summary = _get(client, path, tenants.viewer)
    assert state == "MISS" and summary["tasks"]["by_status"]["todo"] == 1


def test_cache_never_crosses_tenants(
    client: TestClient, tenants: Tenants, acme_board: Board, globex_board: Board
) -> None:
    _get(client, f"/api/v1/organizations/{tenants.acme}/projects", tenants.member)
    state, body = _get(client, f"/api/v1/organizations/{tenants.globex}/projects", tenants.mallory)
    assert state == "MISS"
    assert [p["name"] for p in body["items"]] == ["Secret"]


def test_authorization_runs_before_cache(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    path = f"/api/v1/organizations/{tenants.acme}/projects"
    _get(client, path, tenants.member)  # warm the cache
    assert client.get(path, headers=tenants.mallory.headers).status_code == 404

    # A removed member's still-valid token doesn't reach the cached page either.
    client.delete(
        f"/api/v1/organizations/{tenants.acme}/members/{tenants.viewer.id}",
        headers=tenants.owner.headers,
    )
    assert client.get(path, headers=tenants.viewer.headers).status_code == 404


def test_redis_outage_falls_back_to_database(
    client: TestClient, tenants: Tenants, acme_board: Board, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead = Cache(Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1), ttl_seconds=60)
    monkeypatch.setattr(cache, "get_cache", lambda: dead)

    for _ in range(2):
        state, body = _get(client, f"/api/v1/organizations/{tenants.acme}/projects", tenants.member)
        assert state == "MISS" and body["total"] == 1
    # Writes still succeed; their invalidation is skipped (and logged).
    create_project(client, tenants.member, tenants.acme, acme_board.workspace_id, "Offline-safe")
    _, summary = _get(client, f"/api/v1/organizations/{tenants.acme}/summary", tenants.member)
    assert summary["projects"]["total"] == 2


def test_entries_have_bounded_ttl(client: TestClient, tenants: Tenants) -> None:
    _get(client, f"/api/v1/organizations/{tenants.acme}/workspaces", tenants.member)
    redis = cache.get_cache().client
    entry_keys = [k for k in redis.scan_iter("org:*") if not k.endswith(":gen")]
    assert entry_keys
    assert all(0 < redis.ttl(k) <= 60 for k in entry_keys)
