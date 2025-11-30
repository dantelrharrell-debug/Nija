# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the rest of the app
COPY . .

# Make entrypoint executable
RUN chmod +x ./entrypoint.sh

# Expose port for web server
EXPOSE 5000

# Run entrypoint on container start
ENTRYPOINT ["./entrypoint.sh"]
