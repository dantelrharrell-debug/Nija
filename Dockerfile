# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libffi-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip, setuptools, wheel
RUN python -m pip install --upgrade pip setuptools wheel

# Copy requirements.txt first to leverage Docker cache
COPY requirements.txt .

# Install standard Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install coinbase_advanced_py directly from GitHub
RUN pip install --no-cache-dir git+https://github.com/dantelrharrell-debug/coinbase_advanced_py.git

# Copy the rest of the app code
COPY . .

# Expose the port Gunicorn will use
EXPOSE 5000

# Set environment variables if needed (example)
# ENV COINBASE_API_KEY="your_api_key"
# ENV COINBASE_API_SECRET="your_api_secret"

# Start Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]

