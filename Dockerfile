# Use slim Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cached layer)
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

# Copy the rest of the app
COPY . /app

# Expose port if needed (optional, for HTTP endpoints)
EXPOSE 8000

# Run the bot in the foreground
CMD ["python", "-u", "main.py"]
