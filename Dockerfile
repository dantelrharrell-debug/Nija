# Use Python 3.11 slim base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required to build wheels for cryptography and similar packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    pkg-config \
 && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for better layer caching, then install
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy application source
COPY . /app

# Expose port provided by Railway (default)
ENV PORT=5000
EXPOSE $PORT

# Start the app with gunicorn; adjust "main:app" if your WSGI app is defined elsewhere
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "main:app", "--workers=1", "--threads=2"]
