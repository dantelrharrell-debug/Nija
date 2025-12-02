# ===========================
# Stage 1: Builder
# ===========================
FROM python:3.11-slim AS builder

# Set working directory
WORKDIR /src

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libffi-dev \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip, setuptools, wheel
RUN python -m pip install --upgrade pip setuptools wheel

# Clone your main Nija repo
RUN git clone --depth 1 https://github.com/dantelrharrell-debug/Nija.git Nija

# Install Python dependencies, including coinbase_advanced_py directly from GitHub
RUN pip install --no-cache-dir \
        PyJWT \
        backoff \
        certifi \
        cffi \
        cryptography \
        idna \
        urllib3 \
        websockets \
        charset_normalizer \
        pycparser \
        git+https://github.com/dantelrharrell-debug/coinbase_advanced_py.git

# ===========================
# Stage 2: Final image
# ===========================
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy bot code
COPY ./bot ./bot

# Copy start.sh
COPY start.sh ./
RUN chmod +x start.sh

# Set environment variable for live trading
ENV LIVE_TRADING=1

# Default command to start bot
CMD ["./start.sh"]
