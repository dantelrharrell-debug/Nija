# Stage 1: build environment
FROM python:3.11-slim AS builder

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Upgrade pip and install wheel/setuptools
RUN python -m pip install --upgrade pip setuptools wheel

# Clone coinbase_advanced_py from GitHub using a GitHub App token
ARG GITHUB_PAT
RUN git clone --depth 1 https://x-access-token:${GITHUB_PAT}@github.com/dantelrharrell-debug/coinbase_advanced_py.git coinbase_advanced_py

# Install coinbase_advanced_py
RUN pip install --no-cache-dir ./coinbase_advanced_py

# Stage 2: runtime environment
FROM python:3.11-slim

WORKDIR /usr/src/app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy bot code
COPY ./bot ./bot
COPY start.sh ./

# Make start script executable
RUN chmod +x start.sh

# Set environment variables (replace via Railway variables)
ENV LIVE_TRADING=1

# Start bot
CMD ["./start.sh"]
