FROM python:3.12-slim

ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1

# Put install context where we will run poetry
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && pip install --upgrade pip setuptools wheel \
 && pip install "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy only the pyproject/lock from the bot/ directory into WORKDIR
COPY bot/pyproject.toml bot/poetry.lock* /app/

# Install dependencies for that pyproject
RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev

# Copy full project (including bot/ code)
COPY . /app

# If your app package is under bot/, set PYTHONPATH or set WORKDIR to that dir:
ENV PYTHONPATH=/app/bot
EXPOSE 5000
CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
