# ---- Builder stage ----
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libffi-dev \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Upgrade pip
RUN python -m pip install --upgrade pip setuptools wheel

# Clone your repo
RUN git clone --depth 1 https://github.com/dantelrharrell-debug/Nija.git Nija

WORKDIR /src/Nija

# Install dependencies
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
    pycparser

# ---- Stage 1: Final image ----
FROM python:3.11-slim

WORKDIR /usr/src/app

# Copy Python packages and binaries from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy your bot code
COPY ./bot ./bot

# Copy start.sh and make it executable
COPY start.sh ./
RUN chmod +x start.sh

# Symlink start_all.sh -> start.sh
RUN ln -s start.sh start_all.sh

# Set container entrypoint
ENTRYPOINT ["./start_all.sh"]
