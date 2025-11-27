# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install coinbase_advanced directly from GitHub
RUN python3 -m pip install git+https://github.com/coinbase/coinbase-advanced-py.git

# Show coinbase_advanced installation (optional for debugging)
RUN python3 -m pip show coinbase_advanced

# Expose Flask port
EXPOSE 5000

# Make start script executable
RUN chmod +x ./start_all.sh

# Default command
CMD ["./start_all.sh"]
