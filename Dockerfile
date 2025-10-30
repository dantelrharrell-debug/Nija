# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /opt/render/project/src

# Copy project files
COPY . .

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Explicitly ensure coinbase-advanced-py is installed
RUN pip install --no-cache-dir coinbase-advanced-py==1.8.2

# Ensure start.sh is executable
RUN chmod +x start.sh

# Expose port if needed
EXPOSE 8080

# Run bot
CMD ["bash", "start.sh"]
