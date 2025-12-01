# Use slim Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install system dependencies and cleanup in one layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy only requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy full app
COPY . .

# Ensure vendor folder is available in PYTHONPATH
ENV PYTHONPATH="/usr/src/app/cd/vendor:$PYTHONPATH"

# Expose app port
EXPOSE 5000

# Run Gunicorn pointing to your WSGI app
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
