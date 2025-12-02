# === Base Image ===
FROM python:3.11-slim

# === System Dependencies ===
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libffi-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# === Upgrade pip and setuptools ===
RUN python -m pip install --upgrade pip setuptools wheel

# === Set working directory ===
WORKDIR /usr/src/app

# === Copy requirements ===
COPY requirements.txt .

# === Install normal Python dependencies ===
RUN pip install --no-cache-dir -r requirements.txt

# === Build argument for GitHub PAT ===
ARG GITHUB_PAT

# === Install private GitHub repo using PAT ===
RUN pip install --no-cache-dir git+https://${GITHUB_PAT}@github.com/dantelrharrell-debug/coinbase_advanced_py.git || \
    echo "coinbase_advanced_py failed to install, continuing with fallback"

# === Copy application code ===
COPY . .

# === Default command ===
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
