# Use Python 3.11-slim for better crypto package support
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy local Python packages if you want to include coinbase_advanced locally
# COPY coinbase_advanced ./coinbase_advanced

# Copy requirements
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --upgrade -r requirements.txt

# Copy the rest of the app
COPY . .

# Make start script executable
RUN chmod +x ./start_all.sh

# Expose port (if needed)
EXPOSE 5000

# Run your app
CMD ["./start_all.sh"]
