# Use slim Python 3.11 image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install git and dependencies for pip
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install coinbase_advanced_py directly from GitHub
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git@main

# Copy the rest of the app
COPY . .

# Expose port for Flask/Gunicorn
EXPOSE 5000

# Start Gunicorn with config
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
