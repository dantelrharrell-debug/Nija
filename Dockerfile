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

# Copy the entire repo so bot/ and any top-level files are present
COPY . /app

# If a root pyproject.toml exists but doesn't have [tool.poetry], rename it so Poetry won't pick it up.
# This preserves the file (renamed) in the image for debugging if needed.
RUN if [ -f /app/pyproject.toml ] && ! grep -q "^\[tool\.poetry\]" /app/pyproject.toml; then mv /app/pyproject.toml /app/pyproject.not-poetry; fi

# Run Poetry install from the bot/ directory (adjust if your project dir name differs)
WORKDIR /app/bot

RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev

# Ensure the app package can be imported
ENV PYTHONPATH=/app

EXPOSE 5000
CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
