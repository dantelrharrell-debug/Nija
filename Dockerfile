# ===========================
# NIJA BOT DOCKERFILE (Render-ready)
# ===========================

# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Environment
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies first for cache
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy app folders
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# Optional copy of cd/ folder (will not fail if missing)
RUN if [ -d /app/cd ]; then cp -r /app/cd /app/cd; fi

# Normalize shell scripts if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

# Lightweight build-time sanity check (warnings only)
RUN set -e; \
    echo "Build sanity checks..."; \
    if [ ! -f /app/web/wsgi.py ]; then echo "WARNING: web/wsgi.py missing"; fi; \
    if [ ! -f /app/app/nija_client/__init__.py ]; then echo "WARNING: app/nija_client/__init__.py missing"; fi; \
    python - <<'PY' || true
import importlib
cands = [
    "app.coinbase_advanced_py.client",
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

# Expose port
EXPOSE 8080

# Start Gunicorn
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
