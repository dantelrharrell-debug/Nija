# ensure constraints.txt is copied already
COPY constraints.txt ./constraints.txt

# make coinbase_adapter available to runtime imports
COPY coinbase_adapter.py ./coinbase_adapter.py

# copy start script and app code after that...
COPY start_all.sh ./start_all.sh
RUN chmod +x ./start_all.sh
COPY bot/ ./bot/
COPY web/ ./web/
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
