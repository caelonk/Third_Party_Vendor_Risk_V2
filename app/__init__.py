"""FastAPI web layer for the Vendor Risk platform.

Imports the shared :mod:`core` domain library and adds multi-tenant persistence
(SQLAlchemy/Postgres), authentication, org-scoping, the JSON API, background
workers, and services. ``core`` never depends on ``app``.
"""
