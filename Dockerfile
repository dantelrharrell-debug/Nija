FROM python:3.11-slim

# Install git and build tools
RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

# Upgrade pip, setuptools, wheel
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install coinbase_advanced_py from GitHub
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Set working directory
WORKDIR /usr/src/app

# Copy only requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 5000

# Start the app with gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
