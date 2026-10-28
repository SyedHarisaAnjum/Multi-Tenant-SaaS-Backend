import logging

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.core.request_context import RequestIdMiddleware
from app.dependencies.auth import DbSession

configure_logging()
logger = logging.getLogger(__name__)

_settings = get_settings()
# Interactive docs and the schema are off in production unless DOCS_ENABLED=true.
_docs = _settings.show_docs
app = FastAPI(
    title=_settings.app_name,
    docs_url="/docs" if _docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs else None,
)
register_exception_handlers(app)
app.add_middleware(RequestIdMiddleware)
app.include_router(api_router)


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """The process is up and serving. No dependencies: a DB outage must not restart it."""
    return {"status": "ok"}


@app.get("/health", tags=["health"])
@app.get("/health/ready", tags=["health"])
def readiness(db: DbSession) -> JSONResponse:
    """Ready for traffic = PostgreSQL answers. Redis is reported but optional: without it
    the cache falls back to the DB and rate limiting fails open."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        logger.exception("Readiness: database unreachable")
        database = "unreachable"
    try:
        get_redis().ping()
        redis = "ok"
    except RedisError:
        logger.warning("Readiness: redis unreachable")
        redis = "unreachable"
    ready = database == "ok"
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ok" if ready else "unavailable", "database": database, "redis": redis},
    )
