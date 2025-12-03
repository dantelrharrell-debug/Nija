# Multi-mode Dockerfile with builder-stage clone for vendor package
# Save this as "Dockerfile" at the repository root and run the docker build command from that directory.

# ---------- Builder (build wheels; will clone vendor if not in build context) ----------
FROM python:3.11-slim AS builder
ARG GITHUB_TOKEN
WORKDIR /src
ENV PIP_NO_CACHE_DIR=1

# Install build tools required to build wheels (keep them only in builder)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/*

# If vendor isn't provided in the build context, clone it (private repo uses GITHUB_TOKEN).
# If vendor is present in the context, COPY later will ensure the local copy is used.
RUN if [ ! -d /src/vendor/coinbase_advanced_py ]; then \
      if [ -n "${GITHUB_TOKEN:-}" ]; then \
        git clone "https://${GITHUB_TOKEN}@github.com/dantelrharrell-debug/coinbase_advanced_py.git" /src/vendor/coinbase_advanced_py ; \
      else \
        git clone "https://github.com/dantelrharrell-debug/coinbase_advanced_py.git" /src/vendor/coinbase_advanced_py ; \
      fi \
    ; fi

# If vendor exists in build context, this COPY will replace the cloned content (local preferred).
COPY vendor/coinbase_advanced_py /src/vendor/coinbase_advanced_py

# Build a wheel for the vendor package
RUN python3 -m pip install --upgrade pip setuptools wheel build \
 && cd /src/vendor/coinbase_advanced_py \
 && python3 -m build --wheel --outdir /wheels .

# ---------- Base runtime (small) ----------
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=production
WORKDIR /usr/src/app

# Copy built wheels from builder stage
COPY --from=builder /wheels /wheels

# Optional: copy requirements if you use one
COPY requirements.txt /usr/src/app/requirements.txt

# Install runtime deps and wheel
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && if ls /wheels/*.whl 1> /dev/null 2>&1; then python3 -m pip install /wheels/*.whl; fi

# Copy app source after installing packages to keep earlier layers cached
COPY . /usr/src/app
RUN chmod +x /usr/src/app/start.sh

# ---------- Dev stage (editable installs + build tools) ----------
FROM builder AS dev
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=development
WORKDIR /usr/src/app

# Copy application source
COPY . /usr/src/app

# Install runtime deps (if present) and then an editable install of vendor package
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && python3 -m pip install --no-deps -e /src/vendor/coinbase_advanced_py

RUN chmod +x /usr/src/app/start.sh

# ---------- Prod stage (final image) ----------
FROM base AS prod
WORKDIR /usr/src/app
CMD ["./start.sh"]
