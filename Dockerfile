# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Remove any old vendor folders just in case
RUN rm -rf ./cd/vendor

# Build provenance and cache control - MUST come BEFORE COPY
ARG CACHE_BUST=2025-12-24-v6-rebuild-trigger-1707
ARG GIT_BRANCH=unknown
ARG GIT_COMMIT=unknown
ENV GIT_BRANCH=${GIT_BRANCH}
ENV GIT_COMMIT=${GIT_COMMIT}

# Copy all project files (cache invalidated by CACHE_BUST above)
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

# Default command: use repo start script to launch bot.py
CMD ["bash", "start.sh"]
