# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for building packages
RUN apt-get update && \
    apt-get install -y build-essential libssl-dev libffi-dev libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy all project files
COPY . /app

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Ensure start.sh is executable
RUN chmod +x start.sh

# Expose health port
EXPOSE 10000

# Entrypoint
CMD ["bash", "start.sh"]
