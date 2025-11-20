# Base image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source code
COPY . .

# Expose port for Railway
ENV PORT=5000
EXPOSE 5000

# Start the web app
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "main:app"]
