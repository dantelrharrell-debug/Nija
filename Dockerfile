# Dockerfile - NIJA Bot (robust, no top-level shell conditionals)
FROM python:3.11-slim

ARG STRICT=0
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
WORKDIR /app

# system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential git ca-certificates dos2unix bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# copy and install requirements (cache-friendly)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# deterministic copies
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# create cd directory and copy if present (don't fail build if absent)
RUN mkdir -p /app/cd
COPY cd/ /app/cd/ 2>/dev/null || true

# normalize scripts if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh || true; chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh || true; chmod +x /app/start_all.sh; fi

# Build-time checks inside a single RUN (shell handles if/else/fi)
RUN set -euo pipefail; \
    echo "Build sanity checks (STRICT=${STRICT})..."; \
    test -f /app/web/wsgi.py || (echo "WARNING: web/wsgi.py missing" && [ "${STRICT}" -eq "1" ] && exit 1 || true); \
    test -f /app/app/nija_client/__init__.py || (echo "WARNING: app/nija_client/__init__.py missing" && [ "${STRICT}" -eq "1" ] && exit 1 || true); \
    \
    if [ -d /app/app/coinbase_advanced_py ] || [ -d /app/cd/vendor/coinbase_advanced_py ] || [ -d /app/cd/coinbase_advanced_py ]; then \
        echo "Found coinbase vendor folder – attempting import test"; \
        python - <<'PY' || (echo "Import check failed" && [ "${STRICT}" -eq "1" ] && exit 1 || true)
import importlib
candidates = [
    "app.coinbase_advanced_py.client",
    "cd.vendor.coinbase_advanced_py.client",
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
    print("WARNING: coinbase vendor present but imports failed for known paths")
    raise SystemExit(2)
PY
    else \
        echo "No coinbase vendor folder detected; skipping coinbase import test"; \
    fi

ENV PORT=8080
EXPOSE 8080

# start web app (gunicorn will serve web.wsgi:application)
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
