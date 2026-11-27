"""Shared context without importing Django models during logging setup."""

from contextvars import ContextVar
from uuid import UUID

# ContextVar isolates concurrent WSGI threads and ASGI tasks without model imports.
correlation_id: ContextVar[UUID | None] = ContextVar("lexflow_correlation_id", default=None)
