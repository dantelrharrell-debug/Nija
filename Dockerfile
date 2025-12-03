# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy project files
COPY . .

# Install OS packages needed to build Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Explicitly install coinbase_advanced_py to system Python
RUN python3 -m pip install --no-cache-dir coinbase_advanced_py==1.8.2

# Install other dependencies
RUN if [ -f requirements.txt ]; then python3 -m pip install --no-cache-dir -r requirements.txt; fi

# Default command: test coinbase_advanced_py import
CMD ["python3", "-c", "import coinbase_advanced_py; print('✅ coinbase_advanced_py found at', coinbase_advanced_py.__file__)"]
