# =========================
# NIJA Bot Dockerfile
# =========================
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        dos2unix \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy entire repo into container
COPY . /app

# =========================
# Build-time sanity checks
# =========================

RUN test -f /app/app/nija_client/__init__.py && \
    test -f /app/web/wsgi.py && \
    test -d /app/cd/vendor/coinbase_advanced_py && \
    test -f /app/cd/vendor/coinbase_advanced_py/client.py && \
    python -c "from cd.vendor.coinbase_advanced_py.client import Client; print('Client import OK')"
# Expose the port your Flask app will run on
ENV PORT=8080
EXPOSE 8080

# =========================
# Gunicorn start
# =========================
# Use Gunicorn with threads
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
