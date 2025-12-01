# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install system dependencies
RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set PYTHONPATH so the container can find vendor modules
ENV PYTHONPATH="/usr/src/app/cd/vendor:$PYTHONPATH"

# Install coinbase_advanced_py in editable mode to bypass pyproject.toml wheel issues
RUN pip install -e /usr/src/app/cd/vendor/coinbase_advanced_py

# Expose the app port
EXPOSE 5000

# Start Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
