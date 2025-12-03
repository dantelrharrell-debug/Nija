# syntax=docker/dockerfile:1.4
# Dockerfile
# Multi-stage build (builder -> base -> dev -> prod)
# - Uses BuildKit secret mount for secure cloning if local vendor is missing.
# Build with:
#   printf "%s" "$GITHUB_TOKEN" > /tmp/github_token && chmod 600 /tmp/github_token
#   DOCKER_BUILDKIT=1 docker build --secret id=github_token,src=/tmp/github_token --target prod -t nija:prod .
#
# Note: do NOT pass tokens via --build-arg in production; use --secret instead.

# ---------- builder: build wheel ----------
FROM python:3.11-slim AS builder

WORKDIR /src
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Build-time system deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Prefer local vendor copy (overrides any clone)
COPY cd/vendor/coinbase_advanced_py /src/vendor/coinbase_advanced_py

# If vendor not in context, securely clone using BuildKit secret mounted at /run/secrets/github_token.
# This RUN uses BuildKit's --mount=type=secret which requires the syntax directive above.
RUN --mount=type=secret,id=github_token,target=/run/secrets/github_token \
    sh -eux -c '\
      if [ -d /src/vendor/coinbase_advanced_py ]; then \
        echo "Using local vendor package"; \
      else \
        if [ -s /run/secrets/github_token ]; then \
          echo "Vendor not present locally; cloning using BuildKit secret..."; \
          git clone --depth 1 "https://$(cat /run/secrets/github_token)@github.com/dantelrharrell-debug/coinbase_advanced_py.git" /src/vendor/coinbase_advanced_py; \
        else \
          echo "Warning: vendor not present and no BuildKit secret provided; proceeding without vendor."; \
        fi; \
      fi'

# Prepare pip build tools and build wheel if vendor exists
RUN python3 -m pip install --upgrade pip setuptools wheel build || true
RUN sh -c 'if [ -d /src/vendor/coinbase_advanced_py ]; then cd /src/vendor/coinbase_advanced_py && python3 -m build --wheel --outdir /wheels .; else echo "No vendor package to build"; fi'

# ---------- base: runtime ----------
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=production

WORKDIR /usr/src/app

# Copy built wheel(s) from builder
COPY --from=builder /wheels /wheels

# Copy requirements early for caching
COPY requirements.txt /usr/src/app/requirements.txt

# Install runtime dependencies and wheel(s)
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && if ls /wheels/*.whl 1> /dev/null 2>&1; then python3 -m pip install /wheels/*.whl; fi

# Copy application source
COPY . /usr/src/app

# Make start.sh executable if present
RUN [ -f /usr/src/app/start.sh ] && chmod +x /usr/src/app/start.sh || true

# ---------- dev: editable install ----------
FROM builder AS dev

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=development

WORKDIR /usr/src/app
COPY . /usr/src/app

RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && if [ -d /src/vendor/coinbase_advanced_py ]; then python3 -m pip install --no-deps -e /src/vendor/coinbase_advanced_py; fi

RUN [ -f /usr/src/app/start.sh ] && chmod +x /usr/src/app/start.sh || true

# ---------- prod: final runtime ----------
FROM base AS prod
WORKDIR /usr/src/app
CMD ["./start.sh"]
