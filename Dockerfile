FROM python:3.11-slim

# Install build deps
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of app
COPY . .

# Default command (can be overridden by Procfile)
CMD ["gunicorn", "app.main:app", "--bind", "0.0.0.0:5000", "--workers", "1"]
