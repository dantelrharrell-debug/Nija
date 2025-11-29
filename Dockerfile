# Dockerfile - NIJA Bot (clean, minimal)
FROM python:3.11-slim

# Basic env
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

# Python deps (copied first for build cache)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy application folders
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/
# If you vendor coinbase-advanced locally, copy it:
# COPY coinbase-advanced/ /app/coinbase-advanced/

# Normalize any shell scripts (if present)
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

# Lightweight build-time sanity check (warnings only)
RUN set -e; \
    echo "Build sanity checks..."; \
    if [ ! -f /app/web/wsgi.py ]; then echo "WARNING: web/wsgi.py missing"; fi; \
    if [ ! -f /app/app/nija_client/__init__.py ]; then echo "WARNING: app/nija_client/__init__.py missing"; fi;

EXPOSE 8080

# Use gunicorn config file for consistent settings
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
