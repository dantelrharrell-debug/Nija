FROM python:3.11-slim

WORKDIR /app

# Install system deps needed for pip building from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential gcc ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and upgrade pip first
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

# Ensure start script is executable
RUN chmod +x start_all.sh

EXPOSE 5000

CMD ["./start_all.sh"]
