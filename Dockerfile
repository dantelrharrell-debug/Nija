# Use the official slim Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for many Python packages and for compiling dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install pip and Python requirements
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Install Coinbase Advanced SDK directly from GitHub (most reliable method)
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Optional: verify package import after install
RUN python -c "from coinbase_advanced.client import Client; print('coinbase_advanced installed ✅')"

# Copy the rest of the source code
COPY . .

# Make your entrypoint script executable (if you have one)
RUN chmod +x /app/start_all.sh

# Set ENTRYPOINT to your start script (adjust if launching with Gunicorn directly)
ENTRYPOINT ["/app/start_all.sh"]
