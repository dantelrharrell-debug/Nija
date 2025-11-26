# ===============================
# NIJA Trading Bot Dockerfile
# ===============================

# Use Python 3.11 slim as base
FROM python:3.11-slim

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies (git required for pip install from Git)
RUN apt-get update && \
    apt-get install -y git build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Copy application files
COPY . /app

# Upgrade pip and install Coinbase Advanced client system-wide
RUN pip install --upgrade pip && \
    pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Install any other Python dependencies from requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || echo "No requirements.txt found, skipping"

# Make start script executable
RUN chmod +x start_all.sh

# Expose port
EXPOSE 5000

# Environment variables for Coinbase (replace in your deployment)
# ENV COINBASE_API_KEY=your_key_here
# ENV COINBASE_API_SECRET=your_secret_here
# ENV COINBASE_API_SUB=your_sub_here

# Start the bot
CMD ["./start_all.sh"]
