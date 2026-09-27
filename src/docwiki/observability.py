import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger("docwiki")


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "event": record.getMessage(),
                "request_id": request_id.get(),
                **getattr(record, "fields", {}),
            }
        )


def configure_logging():
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    for name in ("httpx", "httpcore", "openai", "chromadb"):
        logging.getLogger(name).setLevel(logging.ERROR)


def event(name: str, **fields):
    logger.info(name, extra={"fields": fields})
