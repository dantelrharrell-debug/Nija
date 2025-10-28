# Base image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Install system dependencies (for coinbase, cryptography, etc.)
RUN apt-get update && \
    apt-get install -y build-essential libssl-dev libffi-dev libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy all files into container
COPY . /app

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Ensure start.sh is executable
RUN chmod +x start.sh

# Expose Flask / health endpoint port
EXPOSE 10000

# Environment for Flask health server
ENV FLASK_APP=nija_bot_web.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=10000

# Launch start.sh, which runs run_trader.py
CMD ["bash", "start.sh"]
