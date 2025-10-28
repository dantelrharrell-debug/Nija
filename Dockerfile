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

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Ensure start.sh is executable
RUN chmod +x start.sh

# Expose port if needed (optional)
EXPOSE 8080

# Run bot
CMD ["bash", "start.sh"]
