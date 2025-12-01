# Use Python 3.11 slim
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install git and build tools for Python packages
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for Flask/Gunicorn
EXPOSE 5000

# Start Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
