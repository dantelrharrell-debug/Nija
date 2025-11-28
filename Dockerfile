# =========================
# NIJA Trading Bot Dockerfile
# =========================

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
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install coinbase_advanced directly from GitHub
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Copy application code
COPY . .

# Optional: test if coinbase_advanced installed
RUN python -c "from coinbase_advanced.client import Client; print('coinbase_advanced installed ✅')"

# Expose the port Gunicorn will use
EXPOSE 8080

# Start Gunicorn with your config
CMD ["gunicorn", "-c", "./gunicorn.conf.py", "wsgi:app"]
