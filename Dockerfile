FROM python:3.12-slim

ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && pip install --upgrade pip setuptools wheel \
 && pip install "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy the project's pyproject/lock that live under bot/ into the build context
COPY bot/pyproject.toml bot/poetry.lock* /app/

RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev

# Copy the whole repo
COPY . /app

# If the app package is under bot/ set PYTHONPATH or run gunicorn target accordingly
ENV PYTHONPATH=/app/bot
EXPOSE 5000
CMD ["gunicorn", "bot.web.wsgi:app", "--bind", "0.0.0.0:5000"]
