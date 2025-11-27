# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential gcc libffi-dev musl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (caches pip installs)
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY . /app

# Ensure start script is executable
RUN chmod +x ./start_all.sh

# Start container
CMD ["./start_all.sh"]
