# Dockerfile
FROM python:3.11-slim

# Install system deps used by some Python packages
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

# Copy app files
COPY . /app

# Install base Python deps (do NOT include coinbase-advanced here)
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Make start scripts executable
RUN chmod +x /app/start.sh /app/start_worker.sh

# Use start.sh as the entrypoint (it will install coinbase-advanced at runtime and start gunicorn)
ENTRYPOINT ["/app/start.sh"]
