# Base image
FROM python:3.11-slim

# Non-interactive for apt
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONPATH=/app

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy only requirements first (cache optimization)
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy all application code
COPY . /app

# Fix shell script line endings and make executable
RUN if [ -f ./start_all.sh ]; then dos2unix ./start_all.sh || true; chmod +x ./start_all.sh; fi

# Expose Flask/Gunicorn port
EXPOSE 5000

# Run startup script
CMD ["bash", "-lc", "./start_all.sh"]
