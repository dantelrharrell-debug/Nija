# Start from slim Python 3.11
FROM python:3.11-slim

# Set working directory early
WORKDIR /usr/src/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Upgrade pip, setuptools, wheel
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install coinbase_advanced_py from GitHub
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Copy application code
COPY . .

# Install other Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose Flask port
EXPOSE 5000

# Run Gunicorn with config
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
