# ==============================
# NIJA TRADING BOT - Dockerfile
# ==============================

# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# ------------------------------
# Install system dependencies
# ------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libffi-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------
# Upgrade pip, setuptools, wheel
# ------------------------------
RUN python -m pip install --upgrade pip setuptools wheel

# ------------------------------
# Copy requirements
# ------------------------------
COPY requirements.txt .

# ------------------------------
# Install Python dependencies
# ------------------------------
RUN pip install --no-cache-dir -r requirements.txt

# ------------------------------
# Install coinbase_advanced_py from GitHub using PAT
# ------------------------------
# Use build-arg to pass GitHub PAT safely
ARG GITHUB_PAT
RUN pip install --no-cache-dir git+https://${GITHUB_PAT}@github.com/dantelrharrell-debug/coinbase_advanced_py.git

# ------------------------------
# Copy application source code
# ------------------------------
COPY . .

# ------------------------------
# Expose port
# ------------------------------
EXPOSE 5000

# ------------------------------
# Start Gunicorn
# ------------------------------
CMD ["gunicorn", "--config", "gunicorn.conf.py", "web.wsgi:app"]
