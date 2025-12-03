# Multi-mode Dockerfile: builds wheel, supports dev (editable) and prod (wheel) images.
# Usage:
#  - Build prod:  docker build --target prod -t nija:prod .
#  - Build dev:   docker build --target dev  -t nija:dev  .
#  - (Optional) You can also build the builder stage to just produce wheels:
#      docker build --target builder -t nija:builder .
#
# Stages:
#  1) builder - installs build tools and creates a wheel for vendor/coinbase_advanced_py
#  2) base    - runtime base image; installs wheel and app runtime deps (requirements.txt)
#  3) dev     - development image with build tools + editable install (-e)
#  4) prod    - final production image with installed wheel (small runtime)

# ---------- Builder (build wheels) ----------
FROM python:3.11-slim AS builder

WORKDIR /src
ENV PIP_NO_CACHE_DIR=1

# Install build tools required to build wheels (keep them only in builder)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/*

# Copy vendor package into builder and build a wheel
COPY vendor/coinbase_advanced_py /src/vendor/coinbase_advanced_py

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

# If you use requirements.txt in repo root, copy it so we can install runtime deps
# (If not present, the COPY will be a no-op in the RUN below via existence check.)
COPY requirements.txt /usr/src/app/requirements.txt

# Upgrade pip and install runtime deps then the wheel(s)
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && if [ -f /usr/src/app/requirements.txt ]; then python3 -m pip install -r /usr/src/app/requirements.txt; fi \
 && if ls /wheels/*.whl 1> /dev/null 2>&1; then python3 -m pip install /wheels/*.whl; fi

# Copy application source after installing packages to keep earlier layers cached
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

# Entrypoint / CMD
# Ensure start.sh uses exec to run the main python process (e.g. exec python3 -m bot.live_trading)
CMD ["./start.sh"]
