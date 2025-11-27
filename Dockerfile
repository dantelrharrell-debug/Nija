# ---------------------------
# Base image
# ---------------------------
FROM python:3.11-slim

# ---------------------------
# Environment
# ---------------------------
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PORT=8080
ENV PYTHONPATH=/app/vendor:$PYTHONPATH

# ---------------------------
# Set working directory
# ---------------------------
WORKDIR /app

# ---------------------------
# Copy project files
# ---------------------------
COPY . /app

# ---------------------------
# Install system dependencies
# ---------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------
# Install Python dependencies
# ---------------------------
RUN pip install --upgrade pip
# Install any requirements first if you have requirements.txt
RUN if [ -f "requirements.txt" ]; then pip install --no-cache-dir -r requirements.txt; fi
# Install local vendor package
RUN pip install --no-cache-dir -e ./vendor/coinbase_advanced_py

# ---------------------------
# Expose port
# ---------------------------
EXPOSE 8080

# ---------------------------
# Start command
# ---------------------------
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
