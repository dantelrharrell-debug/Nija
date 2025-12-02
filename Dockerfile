# ---------- BUILDER STAGE ----------
FROM python:3.11-slim AS builder

# Install system dependencies needed to build Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libffi-dev \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /src

# Upgrade pip, setuptools, and wheel
RUN python -m pip install --upgrade pip setuptools wheel

# Clone your repo
RUN git clone --depth 1 https://github.com/dantelrharrell-debug/Nija.git Nija

# Go into repo
WORKDIR /src/Nija

# Install Python dependencies directly from PyPI (no wheels needed)
RUN pip install --no-cache-dir PyJWT backoff certifi cffi cryptography idna urllib3 websockets charset_normalizer pycparser
