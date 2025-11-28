FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential libssl-dev libffi-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Clone SDK & copy the coinbase_advanced module into /app (not into site-packages)
RUN git clone https://github.com/coinbase/coinbase-advanced-py.git /tmp/coinbase_advanced \
    && cp -r /tmp/coinbase_advanced/coinbase_advanced /app/

# Test that import works now (build will fail if not)
RUN python -c "from coinbase_advanced.client import Client; print('coinbase_advanced import works ✅')"

# Copy the rest of your source code (your app, nija_client.py, etc)
COPY . .

RUN chmod +x /app/start_all.sh

ENTRYPOINT ["/app/start_all.sh"]
