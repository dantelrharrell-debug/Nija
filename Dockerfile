# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies and install
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy project folders in correct order
COPY app /app/app
COPY web /app/web
COPY bot /app/bot
COPY cd /app/cd

# Set PYTHONPATH so imports work
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8080

# Start Gunicorn with your WSGI app
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:application"] 
