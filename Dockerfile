FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN python -m pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt
CMD ["python", "nija_render_worker.py"]

# Use official Python slim image
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

# Copy app files
COPY . /app

# Install base Python deps (do NOT include coinbase-advanced here)
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Make start script executable
RUN chmod +x /app/start_all.sh

# Use start_all.sh as the entrypoint (starts bot + Gunicorn)
ENTRYPOINT ["/app/start_all.sh"]
