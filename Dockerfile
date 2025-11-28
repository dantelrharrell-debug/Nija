# Base image
FROM python:3.11-slim

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        curl \
        wget \
        unzip \
        xz-utils \
        perl \
        ca-certificates \
        && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install core Python packages
RUN python -m pip install --upgrade pip setuptools wheel

# Copy requirements.txt (if you have one)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Coinbase advanced library (if not in requirements.txt)
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Copy all bot files
COPY . .

# Make startup script executable
RUN chmod +x start_all.sh

# Expose Flask port (adjust to match app)
EXPOSE 8080

# Default command to start bot (no terminal needed)
CMD ["./start_all.sh"]
