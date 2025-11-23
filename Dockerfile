FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends     curl     build-essential     git     libssl-dev     libffi-dev     python3-dev     pkg-config     && rm -rf /var/lib/apt/lists/*
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
RUN pip install --no-cache-dir --upgrade pip
COPY bot/ ./bot/
COPY web/ ./web/
COPY web/*.py ./web/
COPY bot/*.py ./bot/
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
COPY docker-compose.yml ./
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt -c constraints.txt
