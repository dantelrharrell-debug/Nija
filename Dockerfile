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

# Copy bot's pyproject and lock for caching
COPY bot/pyproject.toml bot/poetry.lock* /app/bot/

# Install Python dependencies system-wide (no virtualenv)
WORKDIR /app/bot
RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev \
 && rm -rf /root/.cache/pypoetry /root/.cache/pip

# Stage 2: Final (Runtime)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/bot \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Copy installed Python packages and console scripts from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . /app

# Defensive rename: prevent Poetry conflicts if root pyproject exists but is not a Poetry project
RUN if [ -f /app/pyproject.toml ] && ! grep -q "^\[tool\.poetry\]" /app/pyproject.toml; then mv /app/pyproject.toml /app/pyproject.not-poetry; fi

# Cleanup: safely remove caches and bytecode only (do NOT remove .dist-info/.egg-info)
RUN rm -rf /root/.cache/pip /root/.cache/pypoetry \
 && find /usr/local/lib/python3.12/site-packages -name "__pycache__" -type d -exec rm -rf {} + \
 && find /usr/local/lib/python3.12/site-packages -name "*.pyc" -delete \
 && find /usr/local/lib/python3.12/site-packages -name "tests" -type d -exec rm -rf {} + \
 && rm -f /usr/local/bin/pip* /usr/local/bin/easy_install || true

EXPOSE 5000

# Runtime command — ensure this module path is correct for your app
CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
