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

# Copy main app folder
COPY app /app/app

# Copy web folder
COPY web /app/web

# Sanity checks
RUN test -f /app/app/nija_client/__init__.py || (echo "ERROR: nija_client/__init__.py missing" && exit 1)
RUN test -f /app/web/wsgi.py || (echo "ERROR: web/wsgi.py missing" && exit 1)
RUN test -d /app/app/coinbase_advanced_py || (echo "ERROR: coinbase_advanced_py folder missing" && exit 1)
RUN test -f /app/app/coinbase_advanced_py/client.py || (echo "ERROR: client.py missing in coinbase_advanced_py" && exit 1)
RUN python -c "from app.coinbase_advanced_py.client import Client; print('Client import OK')"

# Expose the port your Flask app will run on
ENV PORT=8080
EXPOSE 8080

# =========================
# Gunicorn start
# =========================
CMD ["gunicorn", "--config", "./gunicorn.conf.py", "web.wsgi:application"]
