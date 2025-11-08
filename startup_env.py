import os
from loguru import logger

# Load .env automatically
if os.path.exists(".env"):
    try:
        from dotenv import load_dotenv
        load_dotenv()
        logger.info(".env loaded successfully")
    except Exception:
        logger.warning("python-dotenv not installed, skipping .env load")

# Check Coinbase credentials
required_keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_BASE"]
missing = [k for k in required_keys if not os.getenv(k)]
if missing:
    raise ValueError(f"Missing Coinbase API credentials: {', '.join(missing)}")
