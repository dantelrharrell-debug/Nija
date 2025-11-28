# ===============================
# NIJA Trading Bot Dockerfile
# Fully reliable coinbase_advanced install
# ===============================

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Install coinbase_advanced directly from GitHub (most reliable method)
RUN git clone https://github.com/coinbase/coinbase-advanced-py.git /tmp/coinbase_advanced && \
    pip install --no-cache-dir /tmp/coinbase_advanced && \
    rm -rf /tmp/coinbase_advanced

# Copy app code
COPY . .

# Validate coinbase_advanced installation (fail build if missing)
RUN python -c "from coinbase_advanced.client import Client; print('coinbase_advanced installed ✅')"

# Expose Gunicorn port
EXPOSE 8080

# Start the app with Gunicorn
CMD ["gunicorn", "-c", "./gunicorn.conf.py", "wsgi:app"]
