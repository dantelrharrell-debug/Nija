# Use official Python image
FROM python:3.11-slim

# Working directory
WORKDIR /app

# Install git so pip can install GitHub packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Upgrade pip
RUN pip install --upgrade pip

# Install ALL Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Make sure start script can run
RUN chmod +x start_all.sh

# Expose Flask port
EXPOSE 5000

# Start gunicorn + bot
CMD ["./start_all.sh"]
