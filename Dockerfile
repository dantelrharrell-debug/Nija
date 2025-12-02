# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y git build-essential curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

RUN pip install --no-cache-dir git+https://github.com/dantelrharrell-debug/coinbase_advanced_py.git@main#egg=coinbase_advanced_py

# Install private repo using SSH
# Requires GIT_SSH_COMMAND via build secret
RUN --mount=type=ssh pip install --no-cache-dir git+ssh://git@github.com/dantelrharrell-debug/coinbase_advanced_py.git@main#egg=coinbase_advanced_py

COPY . .
EXPOSE 8080
CMD ["python", "bot/live_trading.py"]
