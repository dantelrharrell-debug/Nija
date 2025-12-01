# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all app files
COPY . .

# Set Python path to include vendor modules
ENV PYTHONPATH="/usr/src/app/cd/vendor:/usr/src/app:$PYTHONPATH"

# Expose app port
EXPOSE 5000

# Validate coinbase_advanced_py module
RUN if [ -d "/usr/src/app/cd/vendor/coinbase_advanced_py" ]; then \
        echo "coinbase_advanced_py folder exists, ready to import"; \
    else \
        echo "coinbase_advanced_py folder missing, live trading disabled"; \
    fi

# Use Gunicorn with production-appropriate worker settings
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app", \
     "--workers", "4", \
     "--worker-class", "gthread", \
     "--threads", "2", \
     "--bind", "0.0.0.0:5000", \
     "--capture-output", \
     "--log-level", "info"]
