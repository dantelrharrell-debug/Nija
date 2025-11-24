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

# Copy bot's pyproject/lock first (cache-friendly)
COPY bot/pyproject.toml bot/poetry.lock* /app/bot/

# Install Python dependencies system-wide
WORKDIR /app/bot
RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev \
 && rm -rf /root/.cache/pypoetry /root/.cache/pip

# Stage 2: Final Runtime
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/bot \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Ensure runtime TLS certs are present for outbound HTTPS
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages and console scripts from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . /app

# Defensive rename for root pyproject.toml (if present and not a Poetry project)
RUN if [ -f /app/pyproject.toml ] && ! grep -q "^\[tool\.poetry\]" /app/pyproject.toml; then mv /app/pyproject.toml /app/pyproject.not-poetry; fi

# Optional cleanup to reduce image size (safe)
RUN find /usr/local/lib/python3.12/site-packages -name "__pycache__" -type d -exec rm -rf {} + \
 && find /usr/local/lib/python3.12/site-packages -name "*.pyc" -delete \
 && rm -rf /root/.cache/pip /root/.cache/pypoetry || true

EXPOSE 5000

CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
