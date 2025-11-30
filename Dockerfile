# Use official Python 3.11 image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy Python requirements
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the rest of the app
COPY . .

# Install vendored coinbase_advanced module
RUN pip install ./app/cd/vendor/coinbase_advanced_py

# Expose port 5000
EXPOSE 5000

# Use entrypoint script
ENTRYPOINT ["./entrypoint.sh"]
