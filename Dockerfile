# Stage 1: Builder
FROM python:3.12-slim AS builder

ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates git \
 && pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy only bot's pyproject and lock for caching
COPY bot/pyproject.toml bot/poetry.lock* /app/bot/

WORKDIR /app/bot
RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev \
 && rm -rf /root/.cache/pypoetry /root/.cache/pip

# Stage 2: Final runtime
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/bot \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# runtime packages (add libpq5/libjpeg62-turbo etc. if needed)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy installed python packages and console scripts from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy only the bot/ folder (keep image small)
COPY bot/ /app/bot/

# Create non-root user and set permissions
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app \
 && chown -R app:app /app

USER app

EXPOSE 5000
CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
