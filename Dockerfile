# Use lightweight Python 3.11
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install system dependencies for building packages
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Add vendor folder to PYTHONPATH for custom modules
ENV PYTHONPATH="/usr/src/app/cd/vendor:$PYTHONPATH"

# Ensure coinbase_advanced_py is imported if present
# Do not fail build if module cannot be installed from PyPI
RUN if [ -d "/usr/src/app/cd/vendor/coinbase_advanced_py" ]; then \
        echo "coinbase_advanced_py folder exists, ready to import"; \
    else \
        echo "coinbase_advanced_py folder missing, live trading disabled"; \
    fi

# Expose app port
EXPOSE 5000

# Start Gunicorn server
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
