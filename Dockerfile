# Use Python 3.11 slim base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed for building packages
RUN apt-get update && \
    apt-get install -y build-essential libssl-dev libffi-dev libsqlite3-dev wget curl git && \
    rm -rf /var/lib/apt/lists/*

# Copy project files into container
COPY . /app

# Upgrade pip
RUN pip install --upgrade pip

# Install Coinbase package directly from GitHub
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git@main

# Install Flask if requirements.txt missing
RUN pip install --no-cache-dir Flask

# Expose Flask port
EXPOSE 8080

# Set environment variables for Flask
ENV FLASK_APP=nija_bot_web.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=8080

# Start Flask
CMD ["flask", "run"]
