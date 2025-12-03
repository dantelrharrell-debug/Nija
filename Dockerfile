# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

# Set working dir
WORKDIR /usr/src/app

# Install system dependencies required for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    git \
 && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage layer cache
COPY requirements.txt ./requirements.txt

# Upgrade pip and install python deps if requirements.txt exists
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Copy application source
COPY . .

# Environment
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=info

# Replace this with your app's real module / script / entrypoint
CMD ["python", "-m", "src.main"]
