# -----------------------------
# NIJA Trading Bot Dockerfile
# -----------------------------

# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (git for pip installs from GitHub)
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Set environment variable for port
ENV PORT=8080

# Expose port
EXPOSE 8080

# Start Gunicorn using shell form to expand $PORT
CMD ["sh", "-c", "exec gunicorn wsgi:app \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 2 \
  --worker-class gthread \
  --threads 1 \
  --timeout 120 \
  --graceful-timeout 120 \
  --log-level debug \
  --capture-output \
  --enable-stdio-inheritance"]
