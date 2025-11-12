FROM python:3.11-slim

WORKDIR /app
COPY start_bot.py start_bot_main.py nija_client.py nija_balance_helper.py ./

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python3", "start_bot.py"]

FROM python:3.11-slim  # <-- this second FROM is unnecessary/confusing

WORKDIR /app
COPY start_bot.py start_bot_main.py ./

CMD ["python", "start_bot.py"]
