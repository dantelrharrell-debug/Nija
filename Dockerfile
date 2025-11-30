# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . .

# Expose port for Railway
EXPOSE 8080

# Start Gunicorn server
# wsgi:app assumes your Flask instance is called 'app' inside wsgi.py
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "wsgi:app", "--workers", "2", "--threads", "2"]
