# --------------------------
# Stage 1: Builder
# --------------------------
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

# Clone your main project (if needed)
RUN git clone --depth 1 https://github.com/dantelrharrell-debug/Nija.git Nija

WORKDIR /src/Nija

# Copy coinbase_advanced_py module from your repo
COPY ./coinbase_advanced_py ./coinbase_advanced_py

# Install Python dependencies
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
        ./coinbase_advanced_py

# --------------------------
# Stage 2: Final image
# --------------------------
FROM python:3.11-slim

WORKDIR /usr/src/app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy your bot code and start script
COPY ./bot ./bot
COPY start.sh ./

# Make start script executable
RUN chmod +x start.sh

# Default command
CMD ["./start.sh"]
