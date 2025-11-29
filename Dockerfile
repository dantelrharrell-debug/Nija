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

# Copy coinbase_advanced_py safely if exists
RUN if [ -d "/app/app/coinbase_advanced_py" ]; then \
        echo "coinbase_advanced_py found"; \
    else \
        echo "WARNING: coinbase_advanced_py missing"; \
    fi

# Optional sanity check for Flask
RUN test -f /app/web/wsgi.py || echo "WARNING: wsgi.py missing"

# Set environment variables
ENV PORT=8080
EXPOSE 8080

# =========================
# Gunicorn start
# =========================
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
