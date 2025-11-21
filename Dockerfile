# Use Python 3.11 slim base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy root files
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py /app/

# Copy bot folder
COPY bot/ /app/bot/

# Copy web folder
COPY web/ /app/web/

# Upgrade pip and install Python dependencies
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install bot dependencies first
RUN pip install --no-cache-dir -r bot/requirements.txt

# Install web dependencies
RUN pip install --no-cache-dir -r web/requirements.txt

# Expose Flask port
EXPOSE 5000

# Default command
CMD ["python3", "main.py"]
