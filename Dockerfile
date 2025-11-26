# Use slim Python 3.11
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy app files
COPY . /app

# Upgrade pip
RUN pip install --upgrade pip

# Install Python dependencies
# 1) requirements.txt if present
# 2) Coinbase Advanced directly from GitHub
RUN pip install --no-cache-dir -r requirements.txt || echo "No requirements.txt found, skipping"
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git#egg=coinbase-advanced-py

# Make start script executable
RUN chmod +x start_all.sh

# Expose Flask port
EXPOSE 5000

# Start the bot
CMD ["./start_all.sh"]
