# Use Python 3.11 slim
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the rest of your app
COPY . .

# Expose Flask port
EXPOSE 5000

# Make entrypoint executable
RUN chmod +x ./entrypoint.sh

# Start the bot via entrypoint
ENTRYPOINT ["./entrypoint.sh"]
