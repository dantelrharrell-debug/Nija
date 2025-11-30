# Use Python 3.11 slim
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy rest of your app including the vendored Coinbase client
COPY . .

# Add vendored Coinbase client to PYTHONPATH
ENV PYTHONPATH="/app/cd/vendor/coinbase_advanced_py:${PYTHONPATH}"

# Expose Flask port
EXPOSE 5000

# Start the bot via entrypoint script
ENTRYPOINT ["./entrypoint.sh"]
