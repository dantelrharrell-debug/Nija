# Use Python 3.11 slim image
FROM python:3.11-slim

# Install git for metadata injection
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Build arguments for Git metadata
ARG GIT_BRANCH=unknown
ARG GIT_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown

# Inject Git metadata at build time
RUN echo "Injecting build metadata..." && \
    bash inject_git_metadata.sh || \
    echo "Warning: Could not inject git metadata (continuing anyway)"

# Default command: use repo start script to launch bot.py
CMD ["bash", "start.sh"]
