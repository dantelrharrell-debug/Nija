import os
from cryptography.hazmat.primitives import serialization
from nija_client import CoinbaseClient

# Load PEM from file
pem_path = os.environ.get("COINBASE_PEM_PATH")
with open(pem_path, "rb") as f:
    private_key = serialization.load_pem_private_key(
        f.read(),
        password=None,
    )

# Initialize Coinbase client
coinbase = CoinbaseClient(
    api_key=os.environ.get("COINBASE_API_KEY"),
    org_id=os.environ.get("COINBASE_ORG_ID"),
    private_key=private_key,
)

# Start main bot
from app.main import start_bot
start_bot()
