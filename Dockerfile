FROM python:3.11-slim
WORKDIR /app

# System dependencies for building wheels and cryptography + rust toolchain
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain for packages that require it (cryptography wheels may need)
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# Ensure pip is up-to-date
RUN pip install --no-cache-dir --upgrade pip

# Copy constraints file so pip can use it during install
COPY constraints.txt ./constraints.txt

# Copy start script and make it executable
COPY start_all.sh ./start_all.sh
RUN chmod +x ./start_all.sh

# Copy app files
COPY bot/ ./bot/
COPY web/ ./web/
COPY web/*.py ./web/
COPY bot/*.py ./bot/
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
COPY docker-compose.yml ./

# Use constraints during install to avoid long dependency resolution/backtracking
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt -c constraints.txt

# Run the start script as the container entrypoint
ENTRYPOINT ["./start_all.sh"]
