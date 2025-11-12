FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy everything from app folder into /app
COPY app/ ./app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run bot
CMD ["python3", "app/start_bot.py"]
