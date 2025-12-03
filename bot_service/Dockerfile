FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev libffi-dev python3-dev curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir coinbase-advanced-py==1.8.2 \
    && pip install --no-cache-dir -r requirements.txt

# Preflight: Verify coinbase_advanced_py installation
RUN python3 -c "import coinbase_advanced_py; print('✅ coinbase_advanced_py installed at:', coinbase_advanced_py.__file__)" && \
    python3 -c "import sys; print('Python path:', sys.path)"

RUN chmod +x /app/start.sh

ENTRYPOINT ["/app/start.sh"]
