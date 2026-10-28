"""Redis fixed-window rate limiting for abuse-prone endpoints.

Each rule is applied per *dimension* (client IP, target account, authenticated user,
organization), so one noisy IP can't lock everyone out and one attacker can't spread
guesses across IPs against a single account. Identifiers are hashed before use as keys,
so no emails or IPs sit in Redis in clear text.

Client IP comes from `request.client.host`. Behind a reverse proxy, run uvicorn with
`--proxy-headers --forwarded-allow-ips=<proxy address>` so X-Forwarded-For is honored
*only* from that proxy; never parse the header yourself (clients can forge it).

If Redis is down we fail open (log and allow): an outage of an optimization shouldn't
take login down. Flip `fail_open` for stricter environments.
"""

import hashlib
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.exceptions import RateLimitedError
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int


LOGIN_PER_IP = RateLimitRule("login:ip", limit=30, window_seconds=5 * 60)
LOGIN_PER_ACCOUNT = RateLimitRule("login:account", limit=10, window_seconds=15 * 60)
REGISTER_PER_IP = RateLimitRule("register:ip", limit=10, window_seconds=60 * 60)
REFRESH_PER_IP = RateLimitRule("refresh:ip", limit=60, window_seconds=60)
INVITE_PER_USER = RateLimitRule("invite:user", limit=30, window_seconds=60 * 60)
INVITE_PER_ORG = RateLimitRule("invite:org", limit=200, window_seconds=24 * 60 * 60)
INVITE_ACCEPT_PER_USER = RateLimitRule("invite_accept:user", limit=10, window_seconds=15 * 60)

# Atomic INCR + set-expiry-on-first-hit; returns [count, seconds until window resets].
_HIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('TTL', KEYS[1])}
"""


class RateLimiter:
    def __init__(self, client: Redis, *, enabled: bool = True, fail_open: bool = True) -> None:
        self.client = client
        self.enabled = enabled
        self.fail_open = fail_open
        self._hit = client.register_script(_HIT_SCRIPT)

    def hit(self, rule: RateLimitRule, identifier: str) -> None:
        """Count one attempt; raise RateLimitedError (429) once over the limit."""
        if not self.enabled:
            return
        digest = hashlib.sha256(identifier.encode()).hexdigest()[:32]
        key = f"rl:{rule.name}:{digest}"
        try:
            count, ttl = self._hit(keys=[key], args=[rule.window_seconds])
        except RedisError as exc:
            logger.warning(
                "Rate limiter unavailable (%s); failing %s",
                exc,
                "open" if self.fail_open else "closed",
            )
            if self.fail_open:
                return
            raise RateLimitedError(rule.window_seconds) from exc
        if int(count) > rule.limit:
            logger.info("Rate limit %s exceeded", rule.name)
            raise RateLimitedError(int(ttl) if int(ttl) > 0 else rule.window_seconds)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_redis(), enabled=get_settings().rate_limit_enabled)


Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]
