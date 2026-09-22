"""Domain core for the Vendor Risk platform.

A dependency-light library (only ``requests`` for the NVD client) that holds the
business logic shared by the API and the background worker:

* :mod:`core.scoring`   — the threat x exposure risk model (pure, no I/O).
* :mod:`core.parser`    — normalize raw NVD CVE JSON into flat records.
* :mod:`core.nvd_client`— synchronous NVD 2.0 client (pagination, backoff, pacing).
* :mod:`core.sync`      — engine-agnostic ingest orchestration.
* :mod:`core.constants` — scope disclaimer, watchlist rule, and shared tokens.

The library is intentionally free of web-framework, ORM, and demo scaffolding so
that it has exactly one home and can be imported unchanged on both sides of the
system.
"""
