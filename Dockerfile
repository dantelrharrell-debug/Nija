# ===============================
# NIJA Trading Bot Dockerfile
# ===============================

# Use Python 3.11 slim as base
FROM python:3.11-slim

# -------------------------------
# Environment settings
# -------------------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# -------------------------------
# Install system dependencies
# -------------------------------
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------
# Copy application files
# -------------------------------
COPY . /app

# -------------------------------
# Upgrade pip and install Python dependencies
# -------------------------------
RUN pip install --upgrade pip

# Install Coinbase Advanced client from GitHub
RUN pip install git+https://github.com/coinbase/coinbase-advanced-py.git@main#egg=coinbase_advanced

# Install other dependencies from requirements.txt if exists
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || echo "No requirements.txt found, skipping"

# -------------------------------
# Ensure scripts are executable
# -------------------------------
RUN chmod +x start_all.sh

# -------------------------------
# Expose Flask port
# -------------------------------
EXPOSE 5000

# -------------------------------
# Environment variables for Coinbase
# -------------------------------
# ENV COINBASE_API_KEY=your_api_key
# ENV COINBASE_API_SECRET=your_api_secret
# ENV COINBASE_API_SUB=your_api_sub

# -------------------------------
# Start the bot
# -------------------------------
CMD ["./start_all.sh"]
