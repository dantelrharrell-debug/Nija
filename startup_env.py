# startup_env.py  -- import this before creating the Coinbase client
import os
import stat
from loguru import logger

# Load local .env for development only
if os.path.exists(".env"):
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
        logger.info(".env loaded for local dev")
    except Exception:
        logger.warning("python-dotenv not available, skipping .env load")

# Write PEM content (if provided) to a secure file before client init
pem = os.getenv("COINBASE_PEM_CONTENT")
if pem:
    pem_path = os.getenv("COINBASE_PEM_PATH", "/tmp/coinbase.pem")
    try:
        # convert escaped newlines \n into real newlines
        with open(pem_path, "w") as f:
            f.write(pem.replace("\\n", "\n"))
        # owner read/write only
        os.chmod(pem_path, 0o600)
        os.environ["COINBASE_PEM_PATH"] = pem_path
        logger.info(f"Wrote PEM to {pem_path}")
    except Exception as e:
        logger.exception("Failed writing PEM: {}", e)
        raise

# Check required Coinbase envs (add PASSPHRASE if your client needs it)
required = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
missing = [k for k in required if not os.getenv(k)]
if missing:
    msg = f"Missing Coinbase API credentials: {', '.join(missing)}"
    logger.error(msg)
    raise SystemExit(msg)

logger.info(f"Coinbase env check passed. LIVE_TRADING={os.getenv('LIVE_TRADING')}")
