FROM python:3.11-slim
WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain (some wheels may need it)
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# Ensure pip is up-to-date
RUN pip install --no-cache-dir --upgrade pip

# Copy constraints so pip can use it
COPY constraints.txt ./constraints.txt

# Copy start script and make executable
COPY start_all.sh ./start_all.sh
RUN chmod +x ./start_all.sh

# Ensure coinbase adapter is available at runtime
COPY coinbase_adapter.py ./coinbase_adapter.py

# Copy application code
COPY bot/ ./bot/
COPY web/ ./web/
COPY web/*.py ./web/
COPY bot/*.py ./bot/
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
COPY docker-compose.yml ./

# Install Python deps using constraints
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt -c constraints.txt

# Run the start script
ENTRYPOINT ["./start_all.sh"]
