FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for crypto and git
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy app source code
COPY . .

# Ensure start script is executable
RUN chmod +x /app/start_all.sh

# Expose port if needed
EXPOSE 5000

# Run the start script
CMD ["/app/start_all.sh"]
