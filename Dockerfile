# ===============================
# NIJA Trading Bot Dockerfile
# ===============================

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY . /app

# Upgrade pip
RUN pip install --upgrade pip

# Install Coinbase Advanced client from correct branch
RUN pip install git+https://github.com/coinbase/coinbase-advanced-py.git#egg=coinbase_advanced

# Install Python dependencies from requirements.txt if exists
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || echo "No requirements.txt found, skipping"

# Ensure start script is executable
RUN chmod +x start_all.sh

# Expose port
EXPOSE 5000

# Start bot
CMD ["./start_all.sh"]
