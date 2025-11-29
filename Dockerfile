# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy project folders
COPY app /app/app
COPY web /app/web
COPY bot /app/bot

# Ensure cd folder exists even if empty
RUN mkdir -p /app/cd
COPY cd/* /app/cd/ 2>/dev/null || true

# Set PYTHONPATH
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8080

# Start Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:application"]
