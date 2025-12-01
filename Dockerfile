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
RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

# ----------------------------
# Copy requirements and install
# ----------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ----------------------------
# Copy application code
# ----------------------------
COPY . .

# ----------------------------
# Copy coinbase_advanced_py vendor package
# ----------------------------
COPY cd/vendor/coinbase_advanced_py /usr/src/app/cd/vendor/coinbase_advanced_py

# Install coinbase_advanced_py via pip (optional but ensures visibility)
RUN pip install /usr/src/app/cd/vendor/coinbase_advanced_py

# ----------------------------
# Set PYTHONPATH to include vendor
# ----------------------------
ENV PYTHONPATH="/usr/src/app/cd/vendor:$PYTHONPATH"

# ----------------------------
# Expose port
# ----------------------------
EXPOSE 5000

# ----------------------------
# Start Gunicorn pointing to your WSGI app
# ----------------------------
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
