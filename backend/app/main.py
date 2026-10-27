import logging

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.dependencies.auth import DbSession

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title=get_settings().app_name)
register_exception_handlers(app)
app.include_router(api_router)


@app.get("/health", tags=["health"])
def health_check(db: DbSession) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check: database unreachable")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "database": "unreachable"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
