# Use Python 3.11 slim image
FROM python:3.11-slim

# Install system dependencies: git and build tools
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the rest of your application
COPY . .

# Expose the port Gunicorn will run on
EXPOSE 5000

# Start the app with Gunicorn
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
