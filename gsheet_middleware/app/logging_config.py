"""Central logging setup: console always, rotating file when LOG_FILE is set."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from .config import Settings

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(settings: Settings) -> None:
    level = getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    handlers: list[logging.Handler] = [logging.StreamHandler()]  # console
    if settings.log_file:
        # Ensure the target directory exists (e.g. /var/log/gsheet-middleware/).
        directory = os.path.dirname(os.path.abspath(settings.log_file))
        if directory:
            os.makedirs(directory, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                settings.log_file,
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
                encoding="utf-8",
            )
        )

    root = logging.getLogger()
    root.setLevel(level)
    # Replace any existing handlers so we don't duplicate lines on reload.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root.addHandler(handler)

    # Route uvicorn's own loggers through the root handlers (so access/error
    # lines also land in the file) instead of uvicorn's private handlers.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
