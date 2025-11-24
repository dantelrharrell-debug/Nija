FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install git and other dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Ensure start_all.sh is executable
RUN chmod +x /app/start_all.sh

# Default command
CMD ["/app/start_all.sh"]
