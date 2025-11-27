# Use Python 3.11 slim base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        gcc \
        libffi-dev \
        musl-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose Flask default port
EXPOSE 5000

# Start the app
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "web_service:app"]
