# Use Python 3.11 slim base image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Avoid copying old vendor files
COPY . .

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Install Coinbase Advanced module explicitly
RUN python3 -m pip install --no-cache-dir coinbase_advanced_py==1.8.2

# Install other dependencies
RUN if [ -f requirements.txt ]; then python3 -m pip install --no-cache-dir -r requirements.txt; fi

# Expose port if needed
EXPOSE 8080

# Default command to start your bot
CMD ["python3", "./bot/live_bot_script.py"]
