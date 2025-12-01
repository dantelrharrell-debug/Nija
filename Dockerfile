# ----------------------------
# Base image
# ----------------------------
FROM python:3.11-slim

# ----------------------------
# Set working directory
# ----------------------------
WORKDIR /usr/src/app

# ----------------------------
# Install system dependencies
# ----------------------------
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# ----------------------------
# Copy and install Python dependencies
# ----------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ----------------------------
# Copy application code
# ----------------------------
COPY . .

# ----------------------------
# Copy vendor libraries
# ----------------------------
# We include coinbase_advanced_py in vendor but do NOT pip install it
COPY cd/vendor/coinbase_advanced_py /usr/src/app/cd/vendor/coinbase_advanced_py

# ----------------------------
# Set PYTHONPATH to include vendor folder
# ----------------------------
ENV PYTHONPATH="/usr/src/app/cd/vendor:$PYTHONPATH"

# ----------------------------
# Expose port
# ----------------------------
EXPOSE 5000

# ----------------------------
# Start Gunicorn pointing to WSGI app
# ----------------------------
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
