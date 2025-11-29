# NIJA Bot Dockerfile - Render/Railway Ready
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

WORKDIR /app

# System dependencies for cryptography, builds, etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash libffi-dev libssl-dev pkg-config \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt /app/requirements.txt

# Install Python deps
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy project files
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/
COPY cd/vendor/ /app/cd/vendor/

# Normalize shell scripts if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

# Expose port
EXPOSE 8080

# Start Gunicorn with Flask app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "web.wsgi:wsgi_app", \
     "--worker-class", "gthread", "--threads", "1", "--workers", "2", \
     "--log-level", "debug", "--capture-output"]
