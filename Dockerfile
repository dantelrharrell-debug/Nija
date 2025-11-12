FROM python:3.11-slim

WORKDIR /app

# Copy all your app files into the container
COPY app/ ./app   # assuming start_bot.py is inside app/

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run bot
CMD ["python3", "app/start_bot.py"]
