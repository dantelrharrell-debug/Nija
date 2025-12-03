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
RUN python3 -m pip install --no-cache-dir coinbase_advanced_py==1.8.2
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Optional: show installed packages for debug
RUN python3 -m pip list

# Default command
CMD ["python3", "./bot/live_bot_script.py"]
