# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy Python code
COPY start_bot.py start_bot_main.py nija_client.py nija_balance_helper.py ./

# Copy dependencies and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot
CMD ["python3", "start_bot.py"]
