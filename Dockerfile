FROM python:3.11-slim

WORKDIR /app

# Install basic system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential libssl-dev libffi-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy ALL app code and directories (this ensures every .py and folder is present!)
COPY . /app

# Confirm key files exist
RUN test -f /app/nija_client.py
RUN test -f /app/check_funded.py
RUN test -d /app/coinbase_advanced
RUN test -f /app/coinbase_advanced/client.py
RUN test -f /app/coinbase_advanced/__init__.py

# (Optional but recommended) Test import at build time
RUN python -c "from coinbase_advanced.client import Client; print('SDK import works')"

# Make sure start script is executable
RUN chmod +x /app/start_all.sh

ENTRYPOINT ["/app/start_all.sh"]
