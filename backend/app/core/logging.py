import json
import logging
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.request_context import get_request_id

_base_factory = logging.getLogRecordFactory()


def _record_with_request_id(*args: object, **kwargs: object) -> logging.LogRecord:
    # Stamped at creation, so every handler (ours, uvicorn's, a log shipper's) sees it.
    record = _base_factory(*args, **kwargs)
    record.request_id = get_request_id()
    return record


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log shippers (Loki, CloudWatch, Datadog...)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    logging.setLogRecordFactory(_record_with_request_id)
    settings = get_settings()
    level = logging.DEBUG if settings.environment == "development" else logging.INFO
    handler = logging.StreamHandler()
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Our access log replaces uvicorn's, which lacks the request id.
    logging.getLogger("uvicorn.access").disabled = True
