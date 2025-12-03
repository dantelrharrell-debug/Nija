# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy project files (excluding local vendor)
COPY . .

# Upgrade pip and install dependencies
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install --no-cache-dir coinbase_advanced_py==1.8.2
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Expose port if your bot needs it
EXPOSE 8080

# Default entry point
CMD ["python3", "./bot/live_bot_script.py"]
