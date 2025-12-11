# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Remove any old vendor folders just in case
RUN rm -rf ./cd/vendor

# Copy all project files
COPY . .

# Upgrade pip and install dependencies
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install Coinbase SDK and its dependencies
RUN python3 -m pip install --no-cache-dir \
    cryptography>=46.0.0 \
    PyJWT>=2.6.0 \
    requests>=2.31.0 \
    pandas>=2.1.0 \
    numpy>=1.26.0 \
    coinbase-advanced-py==1.8.2

# Install remaining requirements
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Preflight: Verify coinbase installation and imports
RUN python3 -c "from coinbase.rest import RESTClient; print('✅ Coinbase REST client import successful')"

# Optional: show installed packages for debug
RUN python3 -m pip list

# Default command
CMD ["python3", "./bot/live_bot_script/live_trading.py"]
