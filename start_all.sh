# ... earlier content unchanged ...

# Copy constraints file so pip can use it during install
COPY constraints.txt ./constraints.txt

# Copy app files (add start_all.sh here so it exists in image)
COPY start_all.sh ./start_all.sh
RUN chmod +x ./start_all.sh

COPY bot/ ./bot/
COPY web/ ./web/
COPY web/*.py ./web/
COPY bot/*.py ./bot/
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
COPY docker-compose.yml ./

# Use constraints during install to avoid long dependency resolution/backtracking
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt -c constraints.txt

# Make start_all.sh the container entrypoint (runs in foreground)
ENTRYPOINT ["./start_all.sh"]
