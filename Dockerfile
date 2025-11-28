# Dockerfile - minimal, reproducible image for NIJA trading bot
FROM python:3.11-slim

# Ensure apt-get is non-interactive
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies (for building wheels and dos2unix)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better cache)
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY . /app

# Make sure shell scripts are LF and executable
RUN if [ -f ./start_all.sh ]; then dos2unix ./start_all.sh || true; chmod +x ./start_all.sh; fi

# Expose Flask port
EXPOSE 5000

# Run startup script
CMD ["bash", "-lc", "./start_all.sh"]
