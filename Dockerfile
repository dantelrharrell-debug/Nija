# Use official Python 3.11 slim
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# system deps required for some packages (cryptography, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
      git build-essential libssl-dev libffi-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

# copy requirements and upgrade pip
COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel

# install everything in requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

# install Coinbase SDK from PyPI (preferred)
RUN python -m pip install --no-cache-dir coinbase-advanced-py

# build-time check: will fail the build if import doesn't work
RUN python -c "import importlib, sys; spec = importlib.util.find_spec('coinbase_advanced'); print('spec=', spec); import coinbase_advanced.client as c; print('coinbase_advanced import OK')"

# copy app files
COPY . .

# make start script executable (if you use it)
RUN [ -f /app/start_all.sh ] && chmod +x /app/start_all.sh || echo "no start_all.sh"

EXPOSE 8080

# entrypoint (or run gunicorn directly if preferred)
ENTRYPOINT ["/app/start_all.sh"]
