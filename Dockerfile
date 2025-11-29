# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy project directories
COPY app /app/app
COPY web /app/web
COPY bot /app/bot
COPY cd/vendor /app/cd/vendor

# Set PYTHONPATH so imports work correctly
ENV PYTHONPATH=/app

# Optional sanity checks
RUN test -f /app/app/nija_client/__init__.py || (echo "ERROR: nija_client missing" && exit 1)
RUN test -f /app/web/wsgi.py || (echo "ERROR: wsgi.py missing" && exit 1)
