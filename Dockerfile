# Use Python base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy all files into /app
COPY . /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

# Start the bot
CMD ["sh", "-lc", "ls -la /app || true; python -u main.py || python -u app/main.py || tail -f /tmp/nija_started.ok"]
