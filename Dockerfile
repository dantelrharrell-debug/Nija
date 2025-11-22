# Use Python 3.11 slim as the base image
FROM python:3.11-slim

# Ensure noninteractive apt
ENV DEBIAN_FRONTEND=noninteractive

# ------------------------------------------------------------
# Install OS-level build dependencies for cryptography,
# PyJWT[crypto], ecdsa, and Coinbase clients.
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# Install Rust — required to build cryptography if wheels fail
# ------------------------------------------------------------
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# ------------------------------------------------------------
# Workdir
# ------------------------------------------------------------
WORKDIR /app

# ------------------------------------------------------------
# Copy requirements first for Docker cache efficiency
# ------------------------------------------------------------
COPY requirements.txt /app/requirements.txt

# ------------------------------------------------------------
# Upgrade pip and builder tools
# ------------------------------------------------------------
RUN python3 -m pip install --upgrade pip setuptools wheel

# ------------------------------------------------------------
# Install Python dependencies
# ------------------------------------------------------------
RUN pip install --no-cache-dir -r /app/requirements.txt

# ------------------------------------------------------------
# Copy application source code
# ------------------------------------------------------------
COPY . /app

# ------------------------------------------------------------
# Ensure start script is executable
# ------------------------------------------------------------
RUN if [ -f /app/start_all.sh ]; then chmod +x /app/start_all.sh; fi

EXPOSE 5000

# ------------------------------------------------------------
# Default CMD
# ------------------------------------------------------------
CMD ["/app/start_all.sh"]
