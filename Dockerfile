# Vendor Risk Platform — API / worker / beat share this image.
# Pinned to Python 3.12 for reliable binary wheels (psycopg, weasyprint deps).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime libraries for WeasyPrint (PDF export) — pango/cairo/gdk-pixbuf.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        libffi8 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better layer caching), then the package.
COPY pyproject.toml README.md ./
COPY core ./core
COPY app ./app
COPY seed ./seed
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini gunicorn.conf.py ./
# [ops] adds Flower; the same image runs api / worker / beat / migrate / flower.
RUN pip install --upgrade pip && pip install ".[ops]"

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
