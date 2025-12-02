def initialize_coinbase_client() -> Optional[Any]:
    """
    Initialize Coinbase client using ONLY API_KEY and API_SECRET.
    No passphrase required. No simulation. Fully live trading.
    """
    global client

    # Require ONLY key + secret
    if not (API_KEY and API_SECRET):
        logger.warning("Missing COINBASE_API_KEY or COINBASE_API_SECRET. Live trading disabled.")
        client = None
        return None

    # Try coinbase_advanced_py first
    try:
        from coinbase_advanced_py.client import Client as AdvancedClient
        logger.info("coinbase_advanced_py detected. Initializing advanced client...")
        client = AdvancedClient(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("Advanced Coinbase client initialized successfully. LIVE TRADING ENABLED.")
        return client
    except Exception as e:
        logger.warning(f"coinbase_advanced_py failed: {e}. Falling back to official client...")

    # Fallback → official coinbase client
    try:
        from coinbase.wallet.client import Client as WalletClient
        logger.info("Initializing official Coinbase (wallet) client...")
        client = WalletClient(API_KEY, API_SECRET)
        logger.info("Official Coinbase client initialized successfully. LIVE TRADING ENABLED.")
        return client
    except Exception as e:
        logger.error(f"Official client failed: {e}")

    client = None
    logger.error("Could NOT initialize ANY Coinbase client. LIVE TRADING DISABLED.")
    return None
