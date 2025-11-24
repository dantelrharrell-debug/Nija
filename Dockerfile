FROM python:3.12-slim

ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONPATH=/app/bot

WORKDIR /app

# Install system deps & Poetry
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates git \
 && pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# -------------------------
# Copy only bot's pyproject/lock first (cache-friendly)
# -------------------------
COPY bot/pyproject.toml bot/poetry.lock* /app/bot/

# Install Python dependencies system-wide from bot/
WORKDIR /app/bot
RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev \
 && rm -rf /root/.cache/pypoetry /root/.cache/pip

# -------------------------
# Then copy the rest of the repo
# -------------------------
WORKDIR /app
COPY . /app

# Defensive rename: if a root pyproject exists but is not a Poetry project,
# rename it so it won't interfere with tooling (optional but safe)
RUN if [ -f /app/pyproject.toml ] && ! grep -q "^\[tool\.poetry\]" /app/pyproject.toml; then mv /app/pyproject.toml /app/pyproject.not-poetry; fi

# Ensure PYTHONPATH points to bot/
ENV PYTHONPATH=/app/bot

EXPOSE 5000
CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
