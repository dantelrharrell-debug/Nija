# Use an official Python slim image
FROM python:3.11-slim

# Install system-level build deps (needed for cryptography, pandas, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .

# Upgrade pip and install Python deps
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of app
COPY . .

# Set port environment variable and expose it (Railway will set $PORT at runtime)
ENV PORT=5000
EXPOSE 5000

# Default command for container runtime (Procfile will override on Railway if present)
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "main:app"]
