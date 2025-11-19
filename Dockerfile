# Dockerfile.bot
FROM python:3.11-slim

# Install system deps used by some Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      libssl-dev \
      libffi-dev \
      python3-dev \
      curl \
      git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only what the bot needs
COPY bot.py /app/bot.py
COPY requirements.bot.txt /app/requirements.bot.txt
COPY start_bot.sh /app/start_bot.sh

# Install base Python deps (do NOT include coinbase-advanced here; we install it at runtime)
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r /app/requirements.bot.txt

# Make start script executable
RUN chmod +x /app/start_bot.sh

# start_bot.sh will install coinbase-advanced (runtime) using GITHUB_PAT then run bot.py
ENTRYPOINT ["/app/start_bot.sh"]
