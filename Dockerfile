# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy everything
COPY . .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Install vendored coinbase_advanced module
RUN pip install ./cd/vendor/coinbase_advanced_py

# Expose port
EXPOSE 5000

# Entrypoint
ENTRYPOINT ["./entrypoint.sh"]
