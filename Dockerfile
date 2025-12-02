# Base image
FROM python:3.11-slim

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Upgrade pip & install standard packages
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Install private GitHub repo ---
# Step 1: Configure git credential helper to read token from env
ARG GITHUB_PAT
RUN git config --global url."https://${GITHUB_PAT}:@github.com/".insteadOf "https://github.com/"

# Step 2: Install coinbase_advanced_py from GitHub
RUN pip install --no-cache-dir git+https://github.com/dantelrharrell-debug/coinbase_advanced_py.git@main#egg=coinbase_advanced_py

# Copy app code
COPY . .

# Expose port
EXPOSE 8080

# Start your bot
CMD ["python", "bot/live_trading.py"]
