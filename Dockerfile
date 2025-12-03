# ---------- Single Dockerfile: dev / prod modes ----------
# Usage:
#   Prod build: docker build --build-arg MODE=prod -t nija:prod .
#   Dev build:  docker build --build-arg MODE=dev  -t nija:dev  .

FROM python:3.11-slim

# ---------------- ENV ----------------
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=production

# Build mode (dev | prod)
ARG MODE=prod

WORKDIR /usr/src/app

# ---------------- Install build tools (conditionally for dev or prod) ----------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git && \
    rm -rf /var/lib/apt/lists/*

# ---------------- Copy vendor package if exists ----------------
# Use relative path in context: ensure vendor/coinbase_advanced_py is inside build context
COPY vendor/coinbase_advanced_py /usr/src/vendor/coinbase_advanced_py

# Upgrade pip/setuptools/wheel
RUN python3 -m pip install --upgrade pip setuptools wheel

# ---------------- Install package ----------------
# If dev mode, install editable (-e)
# If prod mode, build wheel then install
RUN if [ "$MODE" = "dev" ]; then \
        echo "Dev mode: installing editable package"; \
        if [ -d /usr/src/vendor/coinbase_advanced_py ]; then \
            python3 -m pip install --no-deps -e /usr/src/vendor/coinbase_advanced_py; \
        fi \
    else \
        echo "Prod mode: building and installing wheel"; \
        if [ -d /usr/src/vendor/coinbase_advanced_py ]; then \
            python3 -m pip install build; \
            python3 -m build --wheel --outdir /wheels /usr/src/vendor/coinbase_advanced_py; \
            python3 -m pip install /wheels/*.whl; \
        fi \
    fi

# ---------------- Copy app source ----------------
COPY . /usr/src/app
RUN chmod +x /usr/src/app/start.sh

# ---------------- CMD ----------------
CMD ["./start.sh"]
