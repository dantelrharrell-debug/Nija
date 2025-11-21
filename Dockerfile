FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
    build-essential git libssl-dev libffi-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy bot folder
COPY bot/ /app/bot/

# Install bot dependencies
RUN pip install --no-cache-dir -r /app/bot/requirements.txt

# Copy config and scripts if needed
COPY config.py /app/config.py

# Start script
CMD ["/app/bot/start_bot.sh"]
