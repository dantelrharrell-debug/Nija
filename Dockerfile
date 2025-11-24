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

# COPY full project first so pyproject.toml is definitely present (no cache advantage)
COPY . /app

RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev

ENV PYTHONPATH=/app
EXPOSE 5000
CMD ["gunicorn", "web.wsgi:app", "--bind", "0.0.0.0:5000"]
