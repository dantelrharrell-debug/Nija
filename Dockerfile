FROM python:3.12-slim

ENV POETRY_NO_INTERACTION=1 \
    POETRY_CACHE_DIR="/var/cache/pypoetry"

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && pip install --upgrade pip setuptools wheel \
 && pip install "poetry==1.7.1" \
 # (optional) ensure poetry won't try interactive prompts
 && poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /root/.cache/pypoetry
