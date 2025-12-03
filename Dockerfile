# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy project files
COPY . .

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Install Coinbase advanced explicitly
RUN python3 -m pip install --no-cache-dir coinbase_advanced_py==1.8.2

# Ensure Python can see site-packages
ENV PYTHONPATH=/usr/local/lib/python3.11/site-packages:$PYTHONPATH

# Install other requirements
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Expose port if needed
EXPOSE 8080

# Default entry
CMD ["python3", "./bot/live_bot_script.py"]
