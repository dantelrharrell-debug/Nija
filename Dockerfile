# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Remove any old vendor folders just in case
RUN rm -rf ./cd/vendor

# Copy all project files
COPY . .

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Install coinbase_advanced_py and other requirements
RUN python3 -m pip install --no-cache-dir coinbase-advanced-py==1.8.2
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Preflight: Verify coinbase_advanced_py installation
RUN python3 -c "from coinbase.rest import RESTClient; print('✅ coinbase-advanced-py installed successfully')"

# Optional: show installed packages for debug
RUN python3 -m pip list

# Default command
CMD ["python3", "./bot/live_bot_script.py"]
