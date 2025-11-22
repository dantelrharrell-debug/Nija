# Use Python 3.11 slim as base
FROM python:3.11-slim

# Ensure noninteractive apt
ENV DEBIAN_FRONTEND=noninteractive

# Install OS-level build dependencies needed to compile cryptography and other wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    pkg-config \
    libssl-dev \
    libffi-dev \
    python3-dev \
    ca-certificates \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install rustup (non-interactive) — cryptography may need Rust to build on some platforms
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Copy only requirements first to leverage Docker cache
COPY requirements.txt /app/requirements.txt

# Upgrade pip & install wheel & setuptools first
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install Python deps (this will install cryptography / PyJWT with crypto support if available)
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY . /app

# Make sure start script is executable (adjust name/path if different in your repo)
RUN if [ -f /app/start_all.sh ]; then chmod +x /app/start_all.sh; fi

EXPOSE 5000

# Use startup script if present, otherwise fallback to gunicorn command (adjust module/app as needed)
CMD ["/app/start_all.sh"]
