# Use Python 3.11 slim base (required for Coinbase Advanced SDK)
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for some crypto packages
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose the port Railway provides
ENV PORT=5000
EXPOSE $PORT

# Start the bot via Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "main:app", "--workers=1", "--threads=2"]
