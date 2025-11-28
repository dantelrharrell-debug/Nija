# ===============================
# NIJA Trading Bot Dockerfile
# Optimized for production
# ===============================

# Use official Python 3.11 slim image
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
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip

# Copy requirements and install all Python dependencies, including Coinbase SDK
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: Explicitly install Coinbase Advanced SDK (if not in requirements.txt)
RUN pip install --no-cache-dir coinbase-advanced-py

# Copy application code
COPY . .

# Optional sanity check: verify Coinbase SDK is installed
RUN python -c "from coinbase_advanced.client import Client; print('coinbase_advanced installed ✅')"

# Expose port for Gunicorn
EXPOSE 8080

# Start Gunicorn server using your configuration
CMD ["gunicorn", "-c", "./gunicorn.conf.py", "wsgi:app"]
