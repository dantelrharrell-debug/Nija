# Use official Python 3.11 image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install required packages
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Optional: set environment variables defaults (overridden by Railway)
ENV LOG_LEVEL=INFO

# Command to run preflight and then start bot
CMD ["sh", "-c", "python nija_preflight.py && python nija_startup.py"]
