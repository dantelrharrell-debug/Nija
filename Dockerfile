# Use official Python 3.11 image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source code
COPY . .

# Expose port for Railway
EXPOSE 8080

# Command to run your app (adjust main file if different)
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080"]
