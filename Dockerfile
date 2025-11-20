# Dockerfile
FROM python:3.11-slim

# Install system deps used by some Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      libssl-dev \
      libffi-dev \
      python3-dev \
      curl \
      git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy just requirements first so pip install step is cached when code changes
COPY requirements.txt /app/requirements.txt

# Install base Python deps (includes gunicorn so it's available at runtime)
RUN python -m pip install --upgrade pip setuptools wheel \
 && python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY . /app

# Make start scripts executable
RUN chmod +x /app/start_all.sh /app/start_bot.sh || true

# Entrypoint starts both bot and gunicorn
ENTRYPOINT ["/app/start_all.sh"]
