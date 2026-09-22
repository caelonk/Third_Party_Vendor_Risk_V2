"""Development-only offline seed pipeline.

This package is **not** part of the product runtime. It replays the saved NVD
fixture corpus (or performs a keyless live pull) into a local SQLite database and
renders a static HTML snapshot, so a developer can exercise the domain core
without Postgres, Redis, or an API key. It also carries the synthetic
business-data generator, kept strictly as a dev seed.

The production system uses :mod:`core.sync` with a SQLAlchemy-backed store and
the FastAPI/Celery layers instead.
"""
