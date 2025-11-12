# Base image
FROM python:3.11-slim

# Set working directory inside the container
WORKDIR /app

# Copy your main bot files into /app
COPY start_bot.py ./      # <-- this copies start_bot.py to /app
COPY start_bot_main.py ./ # <-- also copy start_bot_main.py if needed
COPY nija_client.py ./    # your other Python files
COPY nija_balance_helper.py ./ 

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot
CMD ["python3", "start_bot.py"]   # <-- run start_bot.py in /app
