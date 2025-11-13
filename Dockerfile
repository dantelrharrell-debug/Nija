FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy everything to /app
COPY . /app

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

# Use root as WORKDIR (so main.py in root is found)
WORKDIR /

# Run main.py
CMD ["sh", "-c", "ls -la /; python -u main.py || tail -f /tmp/nija_started.ok"]
