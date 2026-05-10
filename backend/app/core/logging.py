"""Structured logging configuration."""

import logging as _stdlib_logging
import sys

import structlog


def configure_logging(debug: bool = False) -> None:
    """Configure structlog for JSON or console output."""
    _stdlib_logging.basicConfig(
        level=_stdlib_logging.DEBUG if debug else _stdlib_logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stdout,
    )
    _stdlib_logging.getLogger("openai").setLevel(_stdlib_logging.WARNING)
    _stdlib_logging.getLogger("httpx").setLevel(_stdlib_logging.WARNING)
    _stdlib_logging.getLogger("httpcore").setLevel(_stdlib_logging.WARNING)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ExtraAdder(),
    ]

    if debug:
        # Pretty console output for development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]
    else:
        # JSON for production
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(10 if debug else 20),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger."""
    return structlog.get_logger(name)
