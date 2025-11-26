FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      git build-essential gcc libssl-dev libffi-dev python3-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN python3 -m pip install --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x ./start_all.sh || true

EXPOSE 8080

CMD ["./start_all.sh"]
