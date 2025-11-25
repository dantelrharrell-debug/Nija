FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y git ca-certificates --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN chmod +x ./start_all.sh || true
RUN python -m pip install --upgrade pip setuptools wheel

RUN python -m pip install --no-cache-dir -r requirements.txt

EXPOSE 5000
CMD ["./start_all.sh"]
