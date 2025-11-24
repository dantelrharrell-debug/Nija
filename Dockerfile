FROM python:3.12-slim

ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1

# We'll run poetry install from /app/bot (adjust if your package dir is different)
WORKDIR /app/bot

# Install system deps and Poetry
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && pip install --upgrade pip setuptools wheel \
 && pip install "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy only the files needed for dependency resolution from the bot/ folder first (cache-friendly)
COPY bot/pyproject.toml bot/poetry.lock* /app/bot/

# Install dependencies in-system (no virtualenv)
RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev

# Copy the rest of the repository (source code)
WORKDIR /app
COPY . /app

# Ensure Python can import your package under /app/bot
ENV PYTHONPATH=/app

# Adjust the gunicorn target if your app module path differs
EXPOSE 5000
CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
