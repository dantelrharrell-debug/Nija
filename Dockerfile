# Use your base image
FROM python:3.11-slim

# Install git and other dependencies
RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install wheel/setuptools
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install coinbase_advanced_py from GitHub
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Set working directory
WORKDIR /usr/src/app

# Copy your app code
COPY . .

# Install any other requirements
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables (optional, or set at runtime)
# ENV COINBASE_API_KEY="your_key"
# ENV COINBASE_API_SECRET="your_secret"
# ENV COINBASE_API_PASSPHRASE="your_passphrase"

# Expose port
EXPOSE 5000

# Run gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
