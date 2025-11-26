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

# Install system dependencies (git required for Coinbase)
RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY . /app

# Upgrade pip
RUN pip install --upgrade pip

# Install Coinbase Advanced client
RUN pip install git+https://github.com/coinbase/coinbase-advanced-py.git@main#egg=coinbase_advanced

# Install dependencies from requirements.txt if present
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || echo "No requirements.txt found, skipping"

# Ensure start_all.sh is executable
RUN chmod +x start_all.sh

# Expose port
EXPOSE 5000

# Set environment variables for Coinbase (replace with your secrets in your platform)
# ENV COINBASE_API_KEY=your_key_here
# ENV COINBASE_API_SECRET=your_secret_here
# ENV COINBASE_API_SUB=your_sub_here

# Start the bot
CMD ["./start_all.sh"]
