FROM python:3.11-slim

# Working directory
WORKDIR /app

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV LIVE_TRADING=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential curl wget unzip xz-utils perl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and core Python packages
RUN python -m pip install --upgrade pip setuptools wheel

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: Git install for latest Coinbase advanced (if not pinned in requirements)
# RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Copy all bot files
COPY . .

# Make startup script executable
RUN chmod +x start_all.sh

# Expose Flask port if your app uses a web interface
EXPOSE 8080

# Default command (no terminal required)
CMD ["./start_all.sh"]
