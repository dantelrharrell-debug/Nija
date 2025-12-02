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

# === Copy application code ===
COPY . .

# === Set environment variable for GitHub PAT at runtime ===
ENV GITHUB_PAT=${GITHUB_PAT}

# === Entrypoint script for runtime private module install ===
COPY entrypoint.sh /usr/src/app/entrypoint.sh
RUN chmod +x /usr/src/app/entrypoint.sh

# === Default command ===
CMD ["/usr/src/app/entrypoint.sh"]
