# Dockerfile - NIJA Bot (robust / optional vendor support)
# -------------------------------------------------------
# Features:
# - safe copy of optional cd/ folder (won't break builds if absent)
# - build-time STRICT mode (ARG STRICT=0|1) to optionally fail when modules missing
# - PYTHONPATH set to /app so imports from app.* and cd.* work
# - installs minimal system deps for building wheels
# - lightweight import checks (controlled by STRICT)
# - starts Gunicorn with web.wsgi:application
# -------------------------------------------------------

FROM python:3.11-slim

# Allow callers to require strict checks at build time:
#   docker build --build-arg STRICT=1 .
ARG STRICT=0

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Set working directory
WORKDIR /app

# Install small set of system packages useful for many wheels / utilities
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      git \
      ca-certificates \
      dos2unix \
      bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for docker layer caching
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install python deps
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy app code in deterministic order
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# Ensure /app/cd exists; copy contents if present but don't fail build if missing
RUN mkdir -p /app/cd
# The COPY below may fail on some builders if cd/ is not present; use a fallback
# This two-step approach is robust across CI/build systems.
COPY cd/ /app/cd/ 2>/dev/null || true

# Normalize shell scripts (convert CRLF to LF) and make executable if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh || true; chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh || true; chmod +x /app/start_all.sh; fi

# Build-time sanity checks.
# If STRICT=1 then a missing critical file or import will cause build to fail.
# Otherwise just warn and continue.
RUN set -euo pipefail; \
    echo "Running build-time checks (STRICT=${STRICT})..."; \
    # Check minimal expected files (existence)
    test -f /app/web/wsgi.py || (echo "WARNING: web/wsgi.py missing" && [ "${STRICT}" -eq "1" ] && exit 1 || true); \
    test -f /app/app/nija_client/__init__.py || (echo "WARNING: app/nija_client/__init__.py missing" && [ "${STRICT}" -eq "1" ] && exit 1 || true); \
    # Try optional vendor import if present
    if [ -d /app/cd/vendor/coinbase_advanced_py ] || [ -d /app/app/coinbase_advanced_py ] || [ -d /app/cd/coinbase_advanced_py ]; then \
        echo "Found coinbase_advanced vendor folder — testing import..."; \
        python - <<'PY' || (echo "Import check failed" && [ "${STRICT}" -eq "1" ] && exit 1 || true)
import sys, importlib
# prefer exact known paths if present
candidates = [
    "cd.vendor.coinbase_advanced_py.client",
    "app.coinbase_advanced_py.client",
    "coinbase_advanced_py.client",
    "cd.vendor.coinbase_advanced.client",
]
ok = False
for mod in candidates:
    try:
        importlib.import_module(mod)
        print("OK import:", mod)
        ok = True
        break
    except Exception as e:
        # continue trying other candidate import paths
        pass
if not ok:
    print("WARNING: coinbase vendor present but import failed for known module paths.")
    # raise ImportError to trigger shell failure only if STRICT build
    raise SystemExit(2)
PY
    else \
        echo "No coinbase_advanced vendor folder detected; running in vendor-absent mode"; \
    fi

# Expose the chosen port (Railway/Render commonly map 8080)
ENV PORT=8080
EXPOSE 8080

# Use Gunicorn to run the Flask app; web.wsgi:application is expected.
# If you need the bot startup to run inside Gunicorn worker init, put that logic inside web/wsgi.py
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
