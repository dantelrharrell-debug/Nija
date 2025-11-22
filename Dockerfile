# Use Python 3.11 slim base image
FROM python:3.11-slim

# metadata
LABEL maintainer="you@example.com"

# Set working directory
WORKDIR /app

# Install basic system dependencies required to build Python packages.
# We include curl because we may need it to install rust (optional).
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      curl \
      git \
      libssl-dev \
      libffi-dev \
      pkg-config \
      python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Optional: install Rust toolchain so cryptography can compile if wheels are not available.
# Comment this block out if you want a smaller image and believe binary wheels will be available.
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y && \
    /bin/bash -lc "source $HOME/.cargo/env" && \
    rm -rf /root/.rustup/toolchains/*/install.log || true

# Make sure pip/setuptools/wheel are up-to-date (do this before pip installs)
RUN python3 -m pip install --upgrade pip setuptools wheel

# Copy app code (copy requirements files first for better layer caching)
COPY bot/requirements.txt ./bot/requirements.txt
COPY web/requirements.txt ./web/requirements.txt

# Copy the rest of the app
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py /app/
COPY bot/ /app/bot/
COPY web/ /app/web/
COPY start_all.sh /app/start_all.sh
RUN chmod +x /app/start_all.sh

# Install Python deps (bot first then web). Use --no-cache-dir to avoid storing cache.
RUN pip install --no-cache-dir -r bot/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

# Expose Flask port
EXPOSE 5000

# Default command
CMD ["/app/start_all.sh"]
