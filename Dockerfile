# ===== NIJA TRADING BOT DOCKERFILE =====
# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including git
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose port (for Gunicorn)
EXPOSE 5000

# Start Gunicorn server
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
