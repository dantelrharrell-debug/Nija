# Use Python 3.11 slim image
FROM python:3.11-slim

# Install git for metadata injection
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r nija && useradd -r -g nija -u 1000 nija

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

# Create necessary directories and set permissions
RUN mkdir -p /app/cache /app/data /app/logs && \
    chown -R nija:nija /app

# Switch to non-root user
USER nija

# Security: Drop all capabilities and run as non-root
# Health check endpoint - use liveness probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/healthz', timeout=5)" || exit 1

# Default command: use repo start script to launch bot.py
CMD ["bash", "start.sh"]
