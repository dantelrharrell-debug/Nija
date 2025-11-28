FROM python:3.11-slim

# Working directory
WORKDIR /app

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV LIVE_TRADING=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential curl wget unzip xz-utils perl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN python -m pip install --upgrade pip setuptools wheel

# Copy requirements and install all dependencies including coinbase_advanced
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot files
COPY . .

# Make startup script executable
RUN chmod +x start_all.sh

# Expose Flask port (for web interface)
EXPOSE 8080

# Start the bot
CMD ["./start_all.sh"]
