# Use Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        dos2unix && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy app code
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# Ensure cd folder exists even if empty, then copy contents
RUN mkdir -p /app/cd
COPY cd/ /app/cd/ || true

# Expose port if running a web service
EXPOSE 8080

# Default command (adjust to your app entrypoint)
CMD ["python", "-m", "app.main"]
