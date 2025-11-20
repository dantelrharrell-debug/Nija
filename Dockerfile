# Base Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for cryptography, numpy, pandas, git
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    libffi-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Upgrade pip and install Python deps
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY . .

# Expose port for Railway
EXPOSE 8080

# Run app
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080"]
