FROM python:3.11-slim
WORKDIR /app
COPY start_bot.py .
COPY nija_client.py .
COPY nija_balance_helper.py .
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python3", "start_bot.py"]

FROM python:3.11-slim
WORKDIR /app
COPY start_bot.py start_bot_main.py ./
CMD ["python", "start_bot.py"]
