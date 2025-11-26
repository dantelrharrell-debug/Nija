# ===============================
# NIJA Trading Bot Dockerfile
# ===============================

# Base image
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
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------
# Copy application files
# -------------------------------
COPY . /app

# -------------------------------
# Upgrade pip
# -------------------------------
RUN pip install --upgrade pip

# -------------------------------
# Install Coinbase Advanced safely
# -------------------------------
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git@main#egg=coinbase_advanced || echo "Coinbase Advanced install failed, continuing..."

# -------------------------------
# Install other dependencies
# -------------------------------
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || echo "No requirements.txt found or failed to install, continuing..."

# -------------------------------
# Ensure scripts are executable
# -------------------------------
RUN chmod +x start_all.sh

# -------------------------------
# Expose Flask port
# -------------------------------
EXPOSE 5000

# -------------------------------
# Coinbase environment variables
# -------------------------------
# ENV COINBASE_API_KEY=your_api_key
# ENV COINBASE_API_SECRET=your_api_secret
# ENV COINBASE_API_SUB=your_api_sub

# -------------------------------
# Start the bot
# -------------------------------
CMD ["./start_all.sh"]
