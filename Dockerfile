# Stage 1: Builder
FROM python:3.12-slim AS builder

ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install build tools & Poetry
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates git \
 && pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy manifest files for dependency caching
COPY pyproject.toml poetry.lock* requirements.txt requirements.bot.txt requirements.web.txt setup.py* /app/

# Detect if Poetry-managed, otherwise fall back to pip + requirements files
RUN if [ -f /app/pyproject.toml ] && grep -q "^\[tool\.poetry\]" /app/pyproject.toml; then \
      echo "INFO: Poetry project detected, installing with poetry..." && \
      poetry config virtualenvs.create false && \
      poetry install --no-root --no-dev ; \
    else \
      echo "INFO: Non-Poetry project, installing with pip from requirements files..." && \
      pip install --upgrade pip setuptools wheel && \
      ( [ -f /app/requirements.txt ] && pip install --no-cache-dir -r /app/requirements.txt || true ) && \
      ( [ -f /app/requirements.bot.txt ] && pip install --no-cache-dir -r /app/requirements.bot.txt || true ) && \
      ( [ -f /app/requirements.web.txt ] && pip install --no-cache-dir -r /app/requirements.web.txt || true ); \
    fi \
 && rm -rf /root/.cache/pypoetry /root/.cache/pip

# Copy full repository
COPY . /app

# Install local package (e.g., coinbase_advanced) so it's available in site-packages
RUN if [ -f /app/pyproject.toml ] && grep -q "^\[tool\.poetry\]" /app/pyproject.toml; then \
      poetry install --no-dev ; \
    else \
      pip install --no-cache-dir -e /app ; \
    fi

# Stage 2: Final runtime image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install runtime OS dependencies
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libpq5 libjpeg62-turbo zlib1g libssl3 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . /app

# Create non-root runtime user
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app \
 && chown -R app:app /app

USER app

# Cleanup bytecode
RUN find /usr/local/lib/python3.12/site-packages -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true \
 && find /usr/local/lib/python3.12/site-packages -name "*.pyc" -delete 2>/dev/null || true

EXPOSE 5000

# Default command - adjust to your WSGI module if needed
CMD ["gunicorn", "web.tradingview_webhook:app", "--bind", "0.0.0.0:5000"]
