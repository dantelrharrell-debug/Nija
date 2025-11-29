# Dockerfile (Railway-friendly)
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV PYTHONPATH=/app

WORKDIR /app

# System deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install deps (will install git+https packages too)
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/
# If you vendor coinbase-advanced (Option B), ensure you COPY it here:
# COPY coinbase-advanced/ /app/coinbase-advanced/

# Normalize scripts if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

# Lightweight sanity checks (warnings only)
RUN set -e; \
    echo "Build sanity checks..."; \
    if [ ! -f /app/web/wsgi.py ]; then echo "WARNING: web/wsgi.py missing"; fi; \
    if [ ! -f /app/app/nija_client/__init__.py ]; then echo "WARNING: app/nija_client/__init__.py missing"; fi; \
    python - <<'PY' || true
import importlib
cands = [
    "coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "cd.vendor.coinbase_advanced.client",
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

# Railway uses $PORT env; gunicorn bind uses it automatically if you pass --bind 0.0.0.0:$PORT
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "web.wsgi:application", "--worker-class", "gthread", "--threads", "1", "--workers", "2"]
