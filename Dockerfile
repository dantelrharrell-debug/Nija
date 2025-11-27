# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements if you have one
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN python -m pip install --upgrade pip
RUN python -m pip install -r requirements.txt

# Install coinbase_advanced directly from GitHub
RUN python -m pip install git+https://github.com/coinbase/coinbase-advanced-py.git

# Copy the rest of the app
COPY . .

# Make start script executable
RUN chmod +x ./start_all.sh

# Expose Flask port
EXPOSE 5000

# Use start script as entry point
CMD ["./start_all.sh"]
