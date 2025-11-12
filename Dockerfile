# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy the app folder
COPY app/ ./app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot
CMD ["python3", "app/start_bot.py"]
