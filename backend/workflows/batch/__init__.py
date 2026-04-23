"""Batch workflows package (Lane B scaffold, Lane C deliverables).

Step 3A — ``exception_queues`` taxonomy is LIVE and declarative.
Step 3B — ``eod_controller`` is NOT YET IMPLEMENTED.
"""

from .exception_queues import (
    DEFAULT_SEVERITY,
    EXCEPTION_TYPES,
    ExceptionRecord,
    ExceptionType,
    Severity,
    build_exception,
)

__all__ = [
    "ExceptionType",
    "Severity",
    "EXCEPTION_TYPES",
    "DEFAULT_SEVERITY",
    "ExceptionRecord",
    "build_exception",
]
