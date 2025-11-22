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

# --- Install Rust for cryptography compilation ---
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# --- Copy requirements files ---
COPY bot/requirements.txt web/requirements.txt ./

# --- Install Python dependencies ---
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt

# --- Copy application source code ---
COPY . .

# --- Expose port for Gunicorn ---
EXPOSE 5000

# --- Command to start the app ---
CMD ["gunicorn", "-b", "0.0.0.0:5000", "main:app"]
