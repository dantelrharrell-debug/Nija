# Use slim Python 3.11 image
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
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies and install
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy application folders
COPY app /app/app
COPY web /app/web
COPY bot /app/bot

# Set Python path so all modules can be found
ENV PYTHONPATH=/app

# Expose port for Gunicorn
EXPOSE 8080

# Start the Gunicorn server with your web app
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:application"]
