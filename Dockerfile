# Dockerfile (replace repo Dockerfile)
FROM python:3.11-slim

# Metadata
LABEL maintainer="Dante Harrell <you@example.com>"

WORKDIR /app

# Install system deps required for building coinbase-advanced-py from git.
# Keep layer small and remove apt lists afterwards.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      git \
      gcc \
      libssl-dev \
      libffi-dev \
      libc-dev \
      ca-certificates \
      curl \
      wget \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt and install at build time (no runtime pip needed)
COPY requirements.txt /app/requirements.txt

# Upgrade pip / wheel and install; no network caching
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r /app/requirements.txt

# Copy application source
COPY . /app

# Ensure start script is executable
RUN chmod +x /app/start_all.sh || true

# Expose the port your app listens on
EXPOSE 5000

# Use a simple, safe entrypoint that launches services
CMD ["/app/start_all.sh"]
