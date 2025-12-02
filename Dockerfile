ENV DEBIAN_FRONTEND=noninteractive

# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy your app files
COPY . .

# Install system dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Use GITHUB_PAT environment variable to install private repo
# Make sure Railway has GITHUB_PAT set in env vars
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir git+https://$GITHUB_PAT@github.com/<your-username>/coinbase_advanced_py.git@main#egg=coinbase_advanced_py

# Install other dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose port for Gunicorn
EXPOSE 5000

# Start Gunicorn
CMD ["gunicorn", "--config", "gunicorn.conf.py", "web.wsgi:app"]
