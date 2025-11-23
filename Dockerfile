
Concrete recommended Dockerfile (safe single-stage) — replace your Dockerfile with this if you don't need multi-stage builds:

```text
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential git libssl-dev libffi-dev python3-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
RUN pip install --no-cache-dir --upgrade pip

COPY constraints.txt ./constraints.txt
COPY start_all.sh ./start_all.sh
RUN chmod +x ./start_all.sh

COPY coinbase_adapter.py ./coinbase_adapter.py
COPY bot/ ./bot/
COPY web/ ./web/
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
COPY docker-compose.yml ./

RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt -c constraints.txt

ENTRYPOINT ["./start_all.sh"]
