# Dockerfile - NIJA Bot (no top-level if/else)
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

WORKDIR /app

# System deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Application code
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# Copy cd/ if present (tolerant)
RUN mkdir -p /app/cd
COPY cd/ /app/cd/ 2>/dev/null || true

# Normalize scripts (if present)
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

# Lightweight build-time checks (warn, don't fail)
RUN set -e; \
    echo "Build sanity checks..."; \
    if [ ! -f /app/web/wsgi.py ]; then echo "WARNING: web/wsgi.py missing"; fi; \
    if [ ! -f /app/app/nija_client/__init__.py ]; then echo "WARNING: app/nija_client/__init__.py missing"; fi; \
    python - <<'PY' || true
import importlib
cands = [
    "app.coinbase_advanced_py.client",
    "app.coinbase_advanced_py",
    "cd.vendor.coinbase_advanced_py.client",
    "coinbase_advanced_py.client",
]
for m in cands:
    try:
        importlib.import_module(m)
        print("Import OK:", m)
        break
    except Exception:
        pass
PY

EXPOSE 8080

CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
