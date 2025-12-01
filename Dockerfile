# Use Python 3.11 slim (or 3.10 if needed)
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install git (needed to clone the repo)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy your requirements.txt
COPY requirements.txt .

# Install Python dependencies including coinbase_advanced directly from GitHub
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app
COPY . .

# Expose port
EXPOSE 5000

# Start Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
