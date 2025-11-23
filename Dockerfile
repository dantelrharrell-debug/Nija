# Copy constraints file so pip can use it during install
COPY constraints.txt ./constraints.txt

# Ensure coinbase_adapter is available at runtime so nija_client can import it
COPY coinbase_adapter.py ./coinbase_adapter.py

# Copy start script and make it executable
COPY start_all.sh ./start_all.sh
RUN chmod +x ./start_all.sh

# Copy app files
COPY bot/ ./bot/
COPY web/ ./web/
COPY web/*.py ./web/
COPY bot/*.py ./bot/
COPY main.py config.py coinbase_trader.py tv_webhook_listener.py nija_client.py ./
COPY docker-compose.yml ./

# Use constraints during install to avoid long dependency resolution/backtracking
RUN pip install --no-cache-dir -r bot/requirements.txt -r web/requirements.txt -c constraints.txt
