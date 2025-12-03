# ---------- Multi-mode Dockerfile ----------
# Usage:
#   Build prod: docker build --build-arg MODE=prod -t nija:prod .
#   Build dev:  docker build --build-arg MODE=dev  -t nija:dev  .

ARG MODE=prod
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIJA_ENV=${MODE}

WORKDIR /usr/src/app

# Install build tools
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git curl \
 && rm -rf /var/lib/apt/lists/*

# Upgrade pip and core build tools
RUN python3 -m pip install --upgrade pip setuptools wheel build

# Copy app source first
COPY . /usr/src/app

# Copy vendor if present
COPY vendor/coinbase_advanced_py /usr/src/vendor/coinbase_advanced_py

# Clone vendor from GitHub if missing
RUN if [ ! -d /usr/src/vendor/coinbase_advanced_py ]; then \
        echo "Vendor not found, cloning from GitHub..."; \
        git clone --depth 1 https://github.com/dantelrharrell-debug/coinbase_advanced_py.git /usr/src/vendor/coinbase_advanced_py; \
    else \
        echo "Using local vendor package"; \
    fi

# Install runtime requirements if present
RUN if [ -f /usr/src/app/requirements.txt ]; then \
        python3 -m pip install -r /usr/src/app/requirements.txt; \
    fi

# ---------- Install coinbase_advanced_py ----------
RUN if [ "$MODE" = "dev" ]; then \
        echo "Dev mode: installing editable"; \
        python3 -m pip install --no-deps -e /usr/src/vendor/coinbase_advanced_py; \
    else \
        echo "Prod mode: building wheel"; \
        python3 -m build --wheel --outdir /wheels /usr/src/vendor/coinbase_advanced_py; \
        python3 -m pip install /wheels/*.whl; \
    fi

# Make start script executable
RUN chmod +x /usr/src/app/start.sh

# Entrypoint
CMD ["./start.sh"]
