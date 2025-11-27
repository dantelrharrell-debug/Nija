# single-stage Dockerfile for Nija app
FROM python:3.11-slim

WORKDIR /app

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PORT=8080
ENV PYTHONPATH=/app/vendor:$PYTHONPATH

# Copy everything
COPY . /app

# Install system deps (minimal)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libssl-dev \
      libffi-dev \
      python3-dev \
      curl \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps (if requirements.txt present)
RUN if [ -f "requirements.txt" ]; then pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt; else pip install --upgrade pip; fi

# Install local vendor package if present (editable)
RUN if [ -d "./vendor/coinbase_advanced_py" ]; then \
      pip install --no-cache-dir -e ./vendor/coinbase_advanced_py || true ; \
    fi

# Ensure start script executable
RUN chmod +x /app/start_all.sh || true

EXPOSE 8080

# Use start script as entrypoint
CMD ["./start_all.sh"]
