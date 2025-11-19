# Use Python 3.11 slim base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for cryptography
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Expose port provided by Railway
ENV PORT=5000
EXPOSE $PORT

# Start the app with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "main:app", "--workers=1", "--threads=2"]
