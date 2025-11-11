# start_bot.py
import os
import sys
from loguru import logger
from nija_client import CoinbaseClient, CoinbaseClientError

def main():
    # Determine mode: Advanced (JWT) if COINBASE_ISS and COINBASE_PEM_CONTENT are set
    use_advanced = bool(os.getenv("COINBASE_ISS") and os.getenv("COINBASE_PEM_CONTENT"))
    mode = "advanced" if use_advanced else "hmac"
    
    logger.info("Starting Nija loader (robust).")
    logger.info("Detected Coinbase mode: {}", mode)

    try:
        client_kwargs = {}
        if mode == "advanced":
            client_kwargs["mode"] = "advanced"
            client_kwargs["base_url"] = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        else:
            # HMAC mode uses default API_BASE or https://api.coinbase.com
            client_kwargs["base_url"] = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        # Initialize client
        client = CoinbaseClient(**client_kwargs)
        logger.info("CoinbaseClient initialized. Base URL: {}", client.base)

        # Test connection
        status, resp = client.test_connection()
        if status == 200:
            logger.success("✅ Connection test succeeded.")
        else:
            logger.error("❌ Connection test failed. Status: {} Response: {}", status, resp)

    except CoinbaseClientError as e:
        logger.error("❌ CoinbaseClient error: {}", e)
        sys.exit(1)
    except Exception as e:
        logger.exception("❌ Unexpected error: {}", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
