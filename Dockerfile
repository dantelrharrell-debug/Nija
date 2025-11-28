FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential libssl-dev libffi-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Install Coinbase SDK manually and patch
RUN git clone https://github.com/coinbase/coinbase-advanced-py.git /tmp/coinbase_advanced
RUN pip install --no-cache-dir /tmp/coinbase_advanced
RUN cp -r /tmp/coinbase_advanced/coinbase_advanced /usr/local/lib/python3.11/site-packages/

RUN python -c "from coinbase_advanced.client import Client; print('coinbase_advanced installed ✅')"

COPY . .

RUN chmod +x /app/start_all.sh

ENTRYPOINT ["/app/start_all.sh"]
