# Dockerfile
FROM python:3.11-slim

# System deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      libssl-dev \
      libffi-dev \
      python3-dev \
      curl \
      git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the app
COPY . /app

# Install base Python deps (do NOT list coinbase-advanced here)
RUN python -m pip install --upgrade pip setuptools wheel \
 && python -m pip install --no-cache-dir -r /app/requirements.txt

# Make start script executable
RUN chmod +x /app/start_all.sh

# ENTRYPOINT will run start_all.sh which installs coinbase-advanced at container start
ENTRYPOINT ["/app/start_all.sh"]
