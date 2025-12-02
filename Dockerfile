# ==============================
# Stage 1: Builder
# ==============================
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

# Upgrade pip and tools
RUN python -m pip install --upgrade pip setuptools wheel

# Clone your Nija repo (if needed)
RUN git clone --depth 1 https://github.com/dantelrharrell-debug/Nija.git Nija

# Install Python packages including your wheel
# The wheel file must be in the project root (next to Dockerfile)
COPY coinbase_advanced_py-1.8.2-py3-none-any.whl .
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
    coinbase_advanced_py-1.8.2-py3-none-any.whl

# ==============================
# Stage 2: Final image
# ==============================
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy your bot code
COPY ./bot ./bot

# Copy start script
COPY start.sh ./
RUN chmod +x start.sh

# Set environment variable for live trading (optional)
ENV LIVE_TRADING=1

# Default entrypoint
CMD ["./start.sh"]
