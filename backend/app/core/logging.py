import logging

from app.core.config import get_settings
from app.core.request_context import get_request_id

_base_factory = logging.getLogRecordFactory()


def _record_with_request_id(*args: object, **kwargs: object) -> logging.LogRecord:
    # Stamped at creation, so every handler (ours, uvicorn's, a log shipper's) sees it.
    record = _base_factory(*args, **kwargs)
    record.request_id = get_request_id()
    return record


def configure_logging() -> None:
    logging.setLogRecordFactory(_record_with_request_id)
    level = logging.DEBUG if get_settings().environment == "development" else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Our access log replaces uvicorn's, which lacks the request id.
    logging.getLogger("uvicorn.access").disabled = True
