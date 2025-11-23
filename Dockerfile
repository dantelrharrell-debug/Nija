# --------------------------
# Base image
# --------------------------
FROM python:3.11-slim

# --------------------------
# Set working directory
# --------------------------
WORKDIR /app

# --------------------------
# Install OS dependencies
# --------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        git \
        libssl-dev \
        libffi-dev \
        python3-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# --------------------------
# Install Rust (if needed by some dependency)
# --------------------------
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# --------------------------
# Upgrade pip
# --------------------------
RUN pip install --no-cache-dir --upgrade pip

# --------------------------
# Copy constraints
# --------------------------
COPY constraints.txt ./constraints.txt

# --------------------------
# Copy entrypoint and make executable
# --------------------------
COPY start_all.sh ./start_all.sh
RUN chmod +x ./start_all.sh

# --------------------------
# Copy project files
# --------------------------
COPY coinbase_adapter.py ./coinbase_adapter.py
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
COPY bot/ ./bot/
COPY bot/*.py ./bot/
COPY web/ ./web/
COPY web/*.py ./web/
COPY docker-compose.yml ./

# --------------------------
# Install Python dependencies
# --------------------------
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt -c constraints.txt

# --------------------------
# Default command to run
# --------------------------
CMD ["./start_all.sh"]
