# Multi-stage Dockerfile — tolerant installer (Poetry or fallback to pip and local package)
# Stage 1: Builder
FROM python:3.12-slim AS builder

ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install build tools & Poetry (Poetry will be used only when appropriate)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates git \
 && pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy manifest files for caching
COPY pyproject.toml poetry.lock* requirements.txt requirements.bot.txt requirements.web.txt /app/

# Copy full repo so local packages (setup.py / src/) are available for pip install fallback
COPY . /app

# Install dependencies: poetry if configured, otherwise pip and install local package /app
RUN if [ -f /app/pyproject.toml ] && grep -q "^\[tool\.poetry\]" /app/pyproject.toml; then \
      poetry config virtualenvs.create false && poetry install --no-root --no-dev ; \
    else \
      pip install --upgrade pip setuptools wheel && \
      ( [ -f /app/requirements.txt ] && pip install --no-cache-dir -r /app/requirements.txt || true ) && \
      ( [ -f /app/requirements.bot.txt ] && pip install --no-cache-dir -r /app/requirements.bot.txt || true ) && \
      ( [ -f /app/requirements.web.txt ] && pip install --no-cache-dir -r /app/requirements.web.txt || true ) && \
      pip install --no-cache-dir /app || true ; \
    fi \
 && rm -rf /root/.cache/pypoetry /root/.cache/pip

# Stage 2: Final runtime
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libpq5 libjpeg62-turbo zlib1g libssl3 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy installed python packages & scripts from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . /app

# Create non-root user and chown
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app \
 && chown -R app:app /app /usr/local/bin /usr/local/lib/python3.12/site-packages

USER app

# Cleanup bytecode only (safe)
RUN find /usr/local/lib/python3.12/site-packages -name "__pycache__" -type d -exec rm -rf {} + \
 && find /usr/local/lib/python3.12/site-packages -name "*.pyc" -delete || true

EXPOSE 5000

CMD ["gunicorn", "web:app", "--bind", "0.0.0.0:5000"]
