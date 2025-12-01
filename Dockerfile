# Start from Python 3.11 slim
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install OS-level build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Cleanup any local copies of coinbase-related packages that could shadow pip installs
RUN rm -rf /usr/src/app/coinbase \
           /usr/src/app/coinbase_advanced \
           /usr/src/app/coinbase-advanced \
           /usr/src/app/coinbase_advanced_py || true

# Upgrade pip, setuptools, wheel
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install coinbase_advanced_py explicitly first to avoid naming conflicts
RUN python3 -m pip install --no-cache-dir \
    git+https://github.com/coinbase/coinbase-advanced-py.git@master#egg=coinbase_advanced_py

# Copy your requirements file (should no longer include coinbase_advanced_py)
COPY requirements.txt .

# Install remaining Python dependencies
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Default command (optional, adjust for your app)
CMD ["python3", "nija_client.py"]
