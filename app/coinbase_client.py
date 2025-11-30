import os
import logging

try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")

def get_coinbase_client():
    if Client is None:
        return None
    
    return Client(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        api_sub=os.environ.get("COINBASE_API_SUB")
    )
