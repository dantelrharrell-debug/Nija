# Dockerfile
# Multi-stage build:
#  - builder: builds wheel for cd/vendor/coinbase_advanced_py (prefers local copy; falls back to BuildKit secret clone)
#  - base:   runtime image that installs wheel and application requirements
#  - dev:    development image with editable install (based on builder)
#  - prod:   final runtime image (based on base)
#
# Important: To allow secure cloning of a private vendor repo, build with BuildKit and pass a secret:
#   DOCKER_BUILDKIT=1 docker build --secret id=github_token,src=/tmp/github_token --target prod -t nija:prod .
#
# If you commit cd/vendor/coinbase_advanced_py in your repo, the local copy will be used and no secret is needed.

# ---------- builder: build wheel ----------
FROM python:3.11-slim AS builder

WORKDIR /src
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Install build-only system deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Prefer a local vendor copy if present in build context (this COPY will overwrite any clone)
COPY cd/vendor/coinbase_advanced_py /src/vendor/coinbase_advanced_py

# If vendor isn't present in the context, securely attempt to clone using BuildKit secret.
# This RUN uses --mount=type=secret to access the secret at /run/secrets/github_token during build.
# If no secret is provided, the step safely continues without cloning.
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

# Prepare pip and build tools; then build a wheel if vendor exists
RUN python3 -m pip install --upgrade pip setuptools wheel build || true
RUN sh -c 'if [ -d /src/vendor/coinbase_advanced_py ]; then cd /src/vendor/coinbase_advanced_py && python3 -m build --wheel --outdir /wheels .; else echo "No vendor package to build"; fi'

# ---------- base: runtime ----------
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=production

WORKDIR /usr/src/app

# Copy built wheel(s) from builder (if any)
COPY --from=builder /wheels /wheels

# Copy requirements early for layer caching
COPY requirements.txt /usr/src/app/requirements.txt

# Install runtime dependencies and wheel(s)
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && if ls /wheels/*.whl 1> /dev/null 2>&1; then python3 -m pip install /wheels/*.whl; fi

# Copy the application source
COPY . /usr/src/app

# Make start.sh executable if present (do not fail if missing)
RUN [ -f /usr/src/app/start.sh ] && chmod +x /usr/src/app/start.sh || true

# ---------- dev: editable install (based on builder) ----------
FROM builder AS dev

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=development

WORKDIR /usr/src/app

# Copy application source into dev image
COPY . /usr/src/app

# Install runtime deps and perform editable install of vendor package if present
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && if [ -d /src/vendor/coinbase_advanced_py ]; then python3 -m pip install --no-deps -e /src/vendor/coinbase_advanced_py; fi

RUN [ -f /usr/src/app/start.sh ] && chmod +x /usr/src/app/start.sh || true

# ---------- prod: final runtime ----------
FROM base AS prod
WORKDIR /usr/src/app
CMD ["./start.sh"]
