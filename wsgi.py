# wsgi.py
# This file is the entrypoint Gunicorn will import as `wsgi:app`
import logging
from startup import check_coinbase_connection
from trading_engine import engine_loop  # imports start the engine logic

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("wsgi")

# run Coinbase check and ensure client present (this will sys.exit on failure)
client = check_coinbase_connection(require_live=True)

# Start engine in a background thread so gunicorn can serve web requests if any.
import threading
engine_thread = threading.Thread(target=engine_loop, daemon=True)
engine_thread.start()

# Minimal WSGI app so Gunicorn has something to serve (200 OK)
def app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'NIJA trading bot running\n']
