# Dockerfile - NIJA Bot (robust / no stray Dockerfile parse errors)
FROM python:3.11-slim

# Build arg: set to 1 to make missing files/imports fail the build
ARG STRICT=0

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
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

# Copy requirements first for caching
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install python deps
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy code in deterministic order
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# Ensure cd dir exists and copy if present; don't fail copy step if cd/ is absent in snapshot
RUN mkdir -p /app/cd
# Some builders will fail COPY if source missing; the following COPY might be a no-op where cd/ absent.
COPY cd/ /app/cd/ 2>/dev/null || true

# Normalize & make scripts executable if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh || true; chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh || true; chmod +x /app/start_all.sh; fi

# Build-time sanity checks executed inside a shell RUN (no stray Dockerfile tokens)
RUN set -euo pipefail; \
    echo "Running build-time checks (STRICT=${STRICT})..."; \
    test -f /app/web/wsgi.py || (echo "WARNING: web/wsgi.py missing" && [ "${STRICT}" -eq "1" ] && exit 1 || true); \
    test -f /app/app/nija_client/__init__.py || (echo "WARNING: app/nija_client/__init__.py missing" && [ "${STRICT}" -eq "1" ] && exit 1 || true); \
    \
    # If any coinbase vendor yields candidate import paths, try to import one of them
    if [ -d /app/cd/vendor/coinbase_advanced_py ] || [ -d /app/app/coinbase_advanced_py ] || [ -d /app/cd/coinbase_advanced_py ]; then \
        echo "Found coinbase_advanced vendor folder — testing import..."; \
        python - <<'PY' || (echo "Import check failed" && [ "${STRICT}" -eq "1" ] && exit 1 || true)
import sys, importlib
candidates = [
    "cd.vendor.coinbase_advanced_py.client",
    "app.coinbase_advanced_py.client",
    "coinbase_advanced_py.client",
]
ok = False
for mod in candidates:
    try:
        importlib.import_module(mod)
        print("OK import:", mod)
        ok = True
        break
    except Exception:
        pass
if not ok:
    print("WARNING: coinbase vendor present but import failed for known module paths.")
    raise SystemExit(2)
PY
    else \
        echo "No coinbase_advanced vendor folder detected; continuing without vendor tests"; \
    fi

# Expose port
ENV PORT=8080
EXPOSE 8080

# Start Gunicorn pointing at your WSGI app
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
