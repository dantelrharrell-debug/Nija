FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy everything
COPY . .

# Add top-level to PYTHONPATH so 'bot' is visible
ENV PYTHONPATH="/app:/:$PYTHONPATH"

# Make entrypoint executable
RUN chmod +x ./entrypoint.sh

# Start Gunicorn
ENTRYPOINT ["./entrypoint.sh"]
