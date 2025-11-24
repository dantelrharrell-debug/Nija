# Use official Python image
FROM python:3.12-slim

# Set workdir
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Ensure logs folder exists
RUN mkdir -p /app/logs

# Make start script executable
RUN chmod +x /app/start_all.sh

# Expose web port
EXPOSE 5000

# Default command
CMD ["/app/start_all.sh"]
