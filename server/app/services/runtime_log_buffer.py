from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from itertools import count
from typing import Any

from app.core.config import settings

_logs: deque[dict[str, Any]] = deque(maxlen=settings.WEBSITE_LOG_BUFFER_SIZE)
_lock = threading.Lock()
_counter = count(1)
_handler_name = "rai_website_runtime_log_buffer"


class RuntimeLogBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            entry = {
                "id": f"runtime-{next(_counter)}",
                "event_type": record.name,
                "severity": record.levelname.upper(),
                "source": "rai_website.server",
                "message": message,
                "metadata_json": {
                    "logger": record.name,
                    "module": record.module,
                    "pathname": record.pathname,
                    "lineno": record.lineno,
                },
                "user_id": None,
                "created_at": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            }
            with _lock:
                _logs.append(entry)
        except Exception:
            self.handleError(record)


def install_runtime_log_handler() -> None:
    root = logging.getLogger()
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    for handler in root.handlers:
        if getattr(handler, "name", None) == _handler_name:
            return

    handler = RuntimeLogBufferHandler(level=logging.INFO)
    handler.name = _handler_name
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)


def get_runtime_logs(limit: int = 200) -> list[dict[str, Any]]:
    limit = max(1, min(limit, settings.WEBSITE_LOG_BUFFER_SIZE))
    with _lock:
        return list(_logs)[-limit:]
