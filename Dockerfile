# Dockerfile - Railway friendly
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps early for cache
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# NOTE: if you do have a cd/ directory, add it manually:
# COPY cd/ /app/cd/

# Normalize scripts if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

# Expose (mostly informative; Railway injects $PORT)
EXPOSE 8080

# Use a Gunicorn config file so bind can read $PORT at runtime
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
