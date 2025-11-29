# Dockerfile - NIJA Bot (Railway-friendly)
FROM python:3.11-slim

# Basic env
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

WORKDIR /app

# System deps required for building cryptography / cffi wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash libffi-dev libssl-dev pkg-config \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for cache
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install Python deps
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/ || true

# Normalize any shell scripts if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

EXPOSE 8080

# Use explicit web.wsgi:application so Gunicorn imports the right module
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "web.wsgi:application", "--worker-class", "gthread", "--threads", "1", "--workers", "2", "--log-level", "debug", "--capture-output"]
