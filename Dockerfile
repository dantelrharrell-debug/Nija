FROM python:3.11-slim

WORKDIR /app

# Copy app folder
COPY app/ ./app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot
CMD ["python3", "app/start_bot.py"]
