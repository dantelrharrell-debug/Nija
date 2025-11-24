# Dockerfile
FROM python:3.12-slim

ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build deps and Poetry
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && pip install --upgrade pip setuptools wheel \
 && pip install "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy entire repo so bot/ and any top-level files are present
COPY . /app

# If a root pyproject.toml exists but doesn't have [tool.poetry], rename it so Poetry won't pick it up.
# Preserve it under /app/pyproject.not-poetry for debugging.
RUN if [ -f /app/pyproject.toml ] && ! grep -q "^\[tool\.poetry\]" /app/pyproject.toml; then mv /app/pyproject.toml /app/pyproject.not-poetry; fi

# Install from bot/ (adjust path if your project folder is named differently)
WORKDIR /app/bot

RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev

ENV PYTHONPATH=/app

EXPOSE 5000
# Adjust the gunicorn module path if your WSGI app lives somewhere else
CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
