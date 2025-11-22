# Dockerfile (place at repo root)
FROM python:3.11-slim

# --- Metadata ---
LABEL maintainer="you@example.com"

# --- Workdir ---
WORKDIR /app

# --- Install system build deps required for cryptography and compiled wheels ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# --- Install Rust (needed by cryptography >=40.x builds) ---
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# --- Optional: upgrade pip to avoid some wheel resolution issues ---
RUN pip install --no-cache-dir --upgrade pip

# --- Copy bot and web dirs preserving structure (so paths remain bot/requirements.txt etc) ---
COPY bot/ ./bot/
COPY web/ ./web/

# --- Install Python deps from both requirements files ---
# Make sure these requirements files are the cleaned ones (no coinbase-advanced)
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt

# --- Copy application source files (only after deps to leverage layer caching) ---
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
# If you have other modules/packages, copy them too:
COPY bot/*.py ./bot/
COPY web/*.py ./web/
COPY docker-compose.yml ./

# --- Expose the port your app listens on ---
EXPOSE 5000

# --- Runtime command ---
# Use the gunicorn entry that matches your main:app WSGI object
CMD ["gunicorn", "-b", "0.0.0.0:5000", "main:app"]
