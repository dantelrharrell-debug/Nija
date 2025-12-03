# syntax=docker/dockerfile:1.4
#
# Multi-stage build:
#  - builder: build wheels for all requirements (and vendor package if present)
#  - final: install wheels and copy app sources
#
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /usr/src/app

# Builder stage: produce wheels so final stage can install without build deps
FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy only what we need to build wheels
COPY requirements.txt ./

# Upgrade pip and make a wheelhouse for faster, reproducible installs
RUN pip install --upgrade pip setuptools wheel \
 && pip wheel --no-deps --wheel-dir /wheels -r requirements.txt

# If a vendored local package is present, build a wheel for it too (optional)
# This lets you vendor cd/vendor/coinbase_advanced_py to avoid private clones during build.
COPY cd/vendor cd/vendor
RUN if [ -d "cd/vendor/coinbase_advanced_py" ]; then \
      pip wheel --no-deps --wheel-dir /wheels cd/vendor/coinbase_advanced_py || true; \
    fi

# Final runtime image
FROM base AS final

# Copy pre-built wheels and install them (no compilers needed in final)
COPY --from=builder /wheels /wheels
RUN if [ -n "$(ls -A /wheels 2>/dev/null || true)" ]; then \
      pip install --no-deps /wheels/*.whl || true; \
    fi

# Copy application source
COPY . .

# If vendor package was not built as a wheel for some reason, install it editable as fallback
RUN if [ -d "cd/vendor/coinbase_advanced_py" ]; then \
      pip install --no-deps -e cd/vendor/coinbase_advanced_py || true; \
    fi

# (Optional) expose port or set entrypoint here. Keep CMD minimal to avoid breaking
# the repo's existing run flow. Replace with your real command if needed:
CMD ["python", "-m", "nija"] 
