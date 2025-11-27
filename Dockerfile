# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for git & builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    gcc \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install (upgrade pip first)
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Install coinbase advanced client directly from GitHub (explicit pip call to avoid egg/name confusion)
# --no-deps prevents pip trying to re-resolve deps; deps are handled by requirements.txt
RUN pip install --no-cache-dir "git+https://github.com/coinbase/coinbase-advanced-py.git@v1.8.2"

# Copy app sources
COPY . .

# Ensure start script is executable
RUN chmod +x start_all.sh

EXPOSE 5000

CMD ["./start_all.sh"]
