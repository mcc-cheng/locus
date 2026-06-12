"""Service-layer exceptions."""

from __future__ import annotations


class ServiceError(Exception):
    """Base for service-layer errors."""


class QueryError(ServiceError):
    """The query was rejected (not a single SELECT, parse error, etc.)."""


class QueryTimeoutError(QueryError):
    """The query exceeded its wall-clock budget and was interrupted."""

    def __init__(self, timeout_s: float) -> None:
        self.timeout_s = timeout_s
        super().__init__(f"query exceeded the {timeout_s:g}s time limit and was cancelled")


class VisualizationError(ServiceError):
    """A chart request was invalid (bad type, missing/incompatible columns)."""
