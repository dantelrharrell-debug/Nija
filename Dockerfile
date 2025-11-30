# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the full project (including bot, web, app, cd)
COPY . .

# Make entrypoint executable
RUN chmod +x ./entrypoint.sh

# Expose port
EXPOSE 5000

# Start Gunicorn via entrypoint
ENTRYPOINT ["./entrypoint.sh"]
