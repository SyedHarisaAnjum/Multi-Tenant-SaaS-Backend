"""Read-through cache for a few read-heavy, tenant-wide responses.

Rules
- Only cache responses that are identical for every member of the organization
  (the route checks membership *before* consulting the cache). If a response ever
  depends on the caller's role or identity, put that in the key or don't cache it.
- Keys embed a per-organization, per-namespace *generation* number. Writers bump the
  generation after committing, which orphans every old entry for that namespace in one
  O(1) step (no key scanning). Orphans expire through their TTL.
- Readers fetch the generation *before* querying PostgreSQL, so a reader racing a
  writer can only store stale data under the old generation, which nobody reads.
- Redis is optional. Every failure is logged and treated as a miss; after a failure we
  skip Redis for a few seconds instead of paying the timeout on every request.
"""

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

# Generations must outlive any entry built on them, or a reset could resurrect old keys.
_GENERATION_TTL_SECONDS = 24 * 60 * 60
_BACKOFF_SECONDS = 5.0


class Cache:
    def __init__(self, client: Redis, ttl_seconds: int) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds
        self._skip_until = 0.0

    # -- public API ------------------------------------------------------------------

    def get_or_load(
        self,
        organization_id: uuid.UUID,
        namespace: str,
        params: dict[str, Any],
        loader: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        """Return (value, was_cache_hit). `loader` must return JSON-serializable data."""
        generation = self._call(self.client.get, self._generation_key(organization_id, namespace))
        if generation is _FAILED:
            return loader(), False

        key = self._entry_key(organization_id, namespace, int(generation or 0), params)
        cached = self._call(self.client.get, key)
        if isinstance(cached, str):
            return json.loads(cached), True

        value = loader()
        self._call(
            self.client.set, key, json.dumps(value, separators=(",", ":")), ex=self.ttl_seconds
        )
        return value, False

    def invalidate(self, organization_id: uuid.UUID, *namespaces: str) -> None:
        """Call *after* the database commit."""

        def bump() -> None:
            pipe = self.client.pipeline(transaction=False)
            for namespace in namespaces:
                key = self._generation_key(organization_id, namespace)
                pipe.incr(key)
                pipe.expire(key, _GENERATION_TTL_SECONDS)
            pipe.execute()

        if self._call(bump) is _FAILED:
            # Entries for this org may be stale until their TTL (bounded) expires.
            logger.warning("Cache invalidation failed for org %s %s", organization_id, namespaces)

    # -- internals -------------------------------------------------------------------

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if time.monotonic() < self._skip_until:
            return _FAILED
        try:
            return fn(*args, **kwargs)
        except RedisError as exc:
            self._skip_until = time.monotonic() + _BACKOFF_SECONDS
            logger.warning("Redis unavailable, falling back to the database: %s", exc)
            return _FAILED

    @staticmethod
    def _generation_key(organization_id: uuid.UUID, namespace: str) -> str:
        return f"org:{organization_id}:{namespace}:gen"

    @staticmethod
    def _entry_key(
        organization_id: uuid.UUID, namespace: str, generation: int, params: dict[str, Any]
    ) -> str:
        page = params.get("page", 1)
        size = params.get("page_size", 0)
        rest = {k: v for k, v in sorted(params.items()) if k not in ("page", "page_size")}
        digest = hashlib.sha256(json.dumps(rest, default=str).encode()).hexdigest()[:16]
        return f"org:{organization_id}:{namespace}:g{generation}:page:{page}:size:{size}:{digest}"


class _Failed:
    pass


_FAILED = _Failed()


@lru_cache
def get_cache() -> Cache:
    return Cache(get_redis(), get_settings().cache_ttl_seconds)


# Namespaces (one generation counter each, per organization).
WORKSPACES = "workspaces"
PROJECTS = "projects"
SUMMARY = "summary"
