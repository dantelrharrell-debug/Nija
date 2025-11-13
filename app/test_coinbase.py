from coinbase.rest import RESTClient
import os
from loguru import logger

api_key = os.environ.get("COINBASE_API_KEY")
api_secret = os.environ.get("COINBASE_PEM_CONTENT")

client = RESTClient(api_key=api_key, api_secret=api_secret)

try:
    accounts = client.get_accounts()
    logger.info(accounts)
except Exception as e:
    logger.error(e)
