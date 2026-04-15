"""Entry point for Claude Sessions UI backend."""

from pathlib import Path

import uvicorn

from backend.app import app  # noqa: F401 — imported so uvicorn.run resolves "backend.app:app"

LOG_FILE = str(Path.home() / ".claude" / "claude-sessions-ui.log")
log_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(asctime)s %(levelprefix)s %(message)s",
        }
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "filename": LOG_FILE,
            "formatter": "default",
        }
    },
    "loggers": {
        "uvicorn": {"handlers": ["file"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["file"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["file"], "level": "INFO", "propagate": False},
    },
}

if __name__ == "__main__":
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8765, reload=False, log_config=log_config)
