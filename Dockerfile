# Base image
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Copy all necessary files
COPY start_bot.py start_bot_main.py nija_client.py nija_balance_helper.py requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot
CMD ["python3", "start_bot.py"]
