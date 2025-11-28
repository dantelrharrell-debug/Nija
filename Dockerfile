# Base image
FROM python:3.11-slim

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        curl \
        wget \
        unzip \
        xz-utils \
        perl \
        ca-certificates \
        && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN python -m pip install --upgrade pip setuptools wheel

# Copy requirements if you have one
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt || echo "Warning: some packages failed to install"

# Copy bot files
COPY . .

# Make startup script executable
RUN chmod +x start_all.sh

# Expose Flask port (if using web interface)
EXPOSE 5000

# Default command
CMD ["./start_all.sh"]
