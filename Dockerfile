# Use full slim Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy project files
COPY . .

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Force installation into system site-packages
RUN python3 -m pip install --no-cache-dir --upgrade coinbase_advanced_py==1.8.2

# Install other requirements
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Expose port if needed
EXPOSE 8080

# Test command
CMD ["python3", "-c", "import coinbase_advanced_py; print('✅ found at', coinbase_advanced_py.__file__)"]
