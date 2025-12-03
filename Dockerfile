# Multi-stage Dockerfile (builder -> runtime)
# Usage:
#  - Prod build (use built wheel): docker build --target prod -t nija:prod .
#  - Dev build (editable install): docker build --build-arg MODE=dev --target dev -t nija:dev .
#  - To clone a private vendor repo securely, use BuildKit secrets:
#      DOCKER_BUILDKIT=1 docker build --target builder --secret id=github_token,src=/path/to/tokenfile -t nija:builder .

# ---------- Builder: build wheel (and optionally clone vendor if not present) ----------
FROM python:3.11-slim AS builder

ARG GITHUB_TOKEN=""
WORKDIR /src
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Install build tools needed only in builder
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# If vendor package is not provided in build context, try cloning using either:
#  - BuildKit secret (preferred): read secret at /run/secrets/github_token in a RUN step (see build command)
#  - Or build-arg GITHUB_TOKEN (less secure)
# The COPY below will override a cloned copy if vendor exists in the context.
# Try to use a secret first if present
RUN set -eux; \
    if [ ! -d /src/vendor/coinbase_advanced_py ]; then \
      if [ -f /run/secrets/github_token ]; then \
        echo "Cloning vendor using BuildKit secret..."; \
        git clone --depth 1 "https://$(cat /run/secrets/github_token)@github.com/dantelrharrell-debug/coinbase_advanced_py.git" /src/vendor/coinbase_advanced_py; \
      elif [ -n "$GITHUB_TOKEN" ]; then \
        echo "Cloning vendor using build-arg token (less secure)..."; \
        git clone --depth 1 "https://$GITHUB_TOKEN@github.com/dantelrharrell-debug/coinbase_advanced_py.git" /src/vendor/coinbase_advanced_py; \
      else \
        echo "No token provided and vendor not in context; proceeding (COPY may override)"; \
      fi \
    fi

# Prefer a local copy if present in build context (this COPY will replace cloned content)
COPY cd/vendor/coinbase_advanced_py /src/vendor/coinbase_advanced_py

# Prepare pip build tools and build a wheel if package is present
RUN python3 -m pip install --upgrade pip setuptools wheel build || true
RUN if [ -d /src/vendor/coinbase_advanced_py ]; then \
      cd /src/vendor/coinbase_advanced_py && python3 -m build --wheel --outdir /wheels . ; \
    else \
      echo "Warning: /src/vendor/coinbase_advanced_py missing; skipping wheel build"; \
    fi

# ---------- Base runtime (small) ----------
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=production

WORKDIR /usr/src/app

# Copy built wheel(s) from builder (if any)
COPY --from=builder /wheels /wheels

# Copy requirements early for caching (if present)
COPY requirements.txt /usr/src/app/requirements.txt

# Install runtime dependencies and wheel(s)
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && if ls /wheels/*.whl 1> /dev/null 2>&1; then python3 -m pip install /wheels/*.whl; fi

# Copy application source
COPY . /usr/src/app

# Ensure start.sh is executable if present
RUN [ -f /usr/src/app/start.sh ] && chmod +x /usr/src/app/start.sh || true

# ---------- Dev image: editable install + build tools (based off builder) ----------
FROM builder AS dev

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=development

WORKDIR /usr/src/app
COPY . /usr/src/app

# Install runtime deps then install editable package from builder path
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && if [ -d /src/vendor/coinbase_advanced_py ]; then python3 -m pip install --no-deps -e /src/vendor/coinbase_advanced_py; fi

RUN [ -f /usr/src/app/start.sh ] && chmod +x /usr/src/app/start.sh || true

# ---------- Prod image (final runtime) ----------
FROM base AS prod
WORKDIR /usr/src/app
CMD ["./start.sh"]
