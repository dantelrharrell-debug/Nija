# Base image
FROM python:3.11-slim

# Working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

# Copy app code
COPY . /app

# Expose port (optional if using Flask API)
EXPOSE 8000

# Run the bot in foreground with unbuffered logs
CMD ["python", "-u", "main.py"]
