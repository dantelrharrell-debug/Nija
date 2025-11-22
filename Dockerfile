# --- Base image ---
FROM python:3.11-slim

# --- Set working directory ---
WORKDIR /app

# --- Install system dependencies for cryptography and other builds ---
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# --- Install Rust (needed for cryptography) ---
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# --- Copy bot and web folders preserving folder structure ---
COPY bot/ ./bot/
COPY web/ ./web/

# --- Install Python dependencies from both requirements.txt ---
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt

# --- Copy the rest of the application code ---
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./

# --- Expose port for Gunicorn ---
EXPOSE 5000

# --- Start the app using Gunicorn ---
CMD ["gunicorn", "-b", "0.0.0.0:5000", "main:app"]
