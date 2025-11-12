# Base image
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Copy everything from app folder
COPY app/ ./app
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run bot
CMD ["python3", "app/start_bot.py"]
