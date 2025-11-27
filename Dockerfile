# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for git & builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements if you have one
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Install coinbase_advanced manually
RUN git clone https://github.com/coinbase/coinbase-advanced-py.git /tmp/coinbase-advanced \
    && pip install /tmp/coinbase-advanced \
    && rm -rf /tmp/coinbase-advanced

# Copy the rest of the app
COPY . .

# Expose Flask port
EXPOSE 5000

# Use start script
CMD ["./start_all.sh"]
