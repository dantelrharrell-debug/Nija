# Use official slim Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy project files
COPY . .

# Install system dependencies for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Install coinbase_advanced_py system-wide
RUN python3 -m pip install --no-cache-dir coinbase_advanced_py==1.8.2

# Install other requirements
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Expose port if needed
EXPOSE 8080

# Entrypoint to test module
CMD ["python3", "-c", "import coinbase_advanced_py; print('✅ coinbase_advanced_py found at', coinbase_advanced_py.__file__)"]
