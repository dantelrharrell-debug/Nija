COPY app/start_bot.py ./          # copies to /app/start_bot.py inside container
COPY app/start_bot_main.py ./     
COPY app/nija_client.py ./        
COPY app/nija_balance_helper.py ./
COPY requirements.txt .           # assuming it's at repo root
