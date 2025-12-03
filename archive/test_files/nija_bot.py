# nija_bot.py
import logging
import time
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_bot")

# Coinbase client factory with fallbacks (tries known names)
def get_advanced_client(pem=None, org_id=None):
    """
    Tries to import and instantiate the Coinbase Advanced client.
    Falls back to a Mock client if import/instantiation fail.
    """
    class MockClient:
        def get_accounts(self):
            return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

        def place_order(self, *args, **kwargs):
            return {"status": "simulated"}

    pem = pem or os.environ.get("COINBASE_PEM_CONTENT")
    org_id = org_id or os.environ.get("COINBASE_ORG_ID")
    # Try a few import paths the package might expose
    candidates = [
        ("coinbase_advanced.client", "AdvancedClient"),
        ("coinbase_advanced.client", "Client"),
        ("coinbase_advanced_py.client", "AdvancedClient"),
        ("coinbase_advanced_py.client", "Client"),
        ("coinbase_advanced", "AdvancedClient"),
    ]
    for module_name, class_name in candidates:
        try:
            mod = __import__(module_name, fromlist=[class_name])
            ClientClass = getattr(mod, class_name)
            logger.info(f"Using Coinbase client from {module_name}.{class_name}")
            # instantiate depending on constructor signature; try common kwargs
            try:
                return ClientClass(pem=pem, org_id=org_id)
            except TypeError:
                try:
                    return ClientClass(pem)
                except Exception:
                    return ClientClass()
        except Exception:
            continue

    logger.warning("Coinbase advanced client not available; using MockClient")
    return MockClient()


# Import your own nija_client.start_bot if you have it
try:
    from nija_client import start_bot  # adapt this to your code's entrypoint
except Exception as e:
    start_bot = None
    logger.warning("nija_client.start_bot not available: %s", e)

def background_loop(client):
    """
    Example 24/7 loop — replace with your bot's real logic.
    """
    while True:
        try:
            accounts = client.get_accounts()
            logger.info("Heartbeat: fetched %d accounts", len(accounts))
        except Exception as e:
            logger.exception("Error fetching accounts: %s", e)
        time.sleep(60)  # pause between heartbeats

def main():
    logger.info("NIJA worker starting")
    client = get_advanced_client()
    # If you have a start_bot function, run it; otherwise run background_loop
    if start_bot:
        logger.info("Calling start_bot() from nija_client")
        try:
            start_bot()  # assume this function blocks / runs the bot
        except Exception:
            logger.exception("start_bot() crashed")
    else:
        logger.info("No start_bot(); starting simple background loop")
        try:
            background_loop(client)
        except Exception:
            logger.exception("Background loop crashed")

if __name__ == "__main__":
    main()# nija_bot.py
import logging
import time
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_bot")

# Coinbase client factory with fallbacks (tries known names)
def get_advanced_client(pem=None, org_id=None):
    """
    Tries to import and instantiate the Coinbase Advanced client.
    Falls back to a Mock client if import/instantiation fail.
    """
    class MockClient:
        def get_accounts(self):
            return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

        def place_order(self, *args, **kwargs):
            return {"status": "simulated"}

    pem = pem or os.environ.get("COINBASE_PEM_CONTENT")
    org_id = org_id or os.environ.get("COINBASE_ORG_ID")
    # Try a few import paths the package might expose
    candidates = [
        ("coinbase_advanced.client", "AdvancedClient"),
        ("coinbase_advanced.client", "Client"),
        ("coinbase_advanced_py.client", "AdvancedClient"),
        ("coinbase_advanced_py.client", "Client"),
        ("coinbase_advanced", "AdvancedClient"),
    ]
    for module_name, class_name in candidates:
        try:
            mod = __import__(module_name, fromlist=[class_name])
            ClientClass = getattr(mod, class_name)
            logger.info(f"Using Coinbase client from {module_name}.{class_name}")
            # instantiate depending on constructor signature; try common kwargs
            try:
                return ClientClass(pem=pem, org_id=org_id)
            except TypeError:
                try:
                    return ClientClass(pem)
                except Exception:
                    return ClientClass()
        except Exception:
            continue

    logger.warning("Coinbase advanced client not available; using MockClient")
    return MockClient()


# Import your own nija_client.start_bot if you have it
try:
    from nija_client import start_bot  # adapt this to your code's entrypoint
except Exception as e:
    start_bot = None
    logger.warning("nija_client.start_bot not available: %s", e)

def background_loop(client):
    """
    Example 24/7 loop — replace with your bot's real logic.
    """
    while True:
        try:
            accounts = client.get_accounts()
            logger.info("Heartbeat: fetched %d accounts", len(accounts))
        except Exception as e:
            logger.exception("Error fetching accounts: %s", e)
        time.sleep(60)  # pause between heartbeats

def main():
    logger.info("NIJA worker starting")
    client = get_advanced_client()
    # If you have a start_bot function, run it; otherwise run background_loop
    if start_bot:
        logger.info("Calling start_bot() from nija_client")
        try:
            start_bot()  # assume this function blocks / runs the bot
        except Exception:
            logger.exception("start_bot() crashed")
    else:
        logger.info("No start_bot(); starting simple background loop")
        try:
            background_loop(client)
        except Exception:
            logger.exception("Background loop crashed")

if __name__ == "__main__":
    main()
