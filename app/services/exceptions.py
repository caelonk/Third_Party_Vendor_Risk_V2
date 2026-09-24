"""Domain exceptions, mapped to HTTP status codes by the app's handlers.

Services raise these instead of importing FastAPI, so the business layer stays
framework-agnostic and testable on its own.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class; carries a human-readable message."""


class ConflictError(DomainError):
    """A uniqueness/state conflict (HTTP 409)."""


class AuthError(DomainError):
    """Invalid credentials or auth failure (HTTP 401)."""


class NotFoundError(DomainError):
    """A referenced resource does not exist (HTTP 404)."""


class PermissionDeniedError(DomainError):
    """The caller lacks the required role/permission (HTTP 403)."""


class ValidationError(DomainError):
    """A business-rule validation failure (HTTP 422)."""


class UnavailableError(DomainError):
    """An upstream dependency (e.g. NVD) is busy or down; try again (HTTP 503)."""
