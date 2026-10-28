from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    settings = get_settings()
    timeout = settings.redis_socket_timeout_seconds
    # Short timeouts: Redis only speeds things up, so a slow or dead Redis must not
    # turn into slow requests.
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
        health_check_interval=30,
    )
