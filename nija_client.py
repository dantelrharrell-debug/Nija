# nija_client.py
"""
Robust Coinbase client bootstrap for Nija trading bot.

Features:
- Writes COINBASE_PEM_CONTENT or COINBASE_JWT_PEM to disk (COINBASE_PEM_PATH) if provided.
- Attempts to import multiple Coinbase client libraries and construct a client.
- Exposes fetch_accounts() for sanity checks.
- Logs useful diagnostics for startup.
"""

import os
import logging
import pathlib
import time
from typing import Optional, Dict, Any

LOG = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# -----------------------
# PEM helper: write PEM content (if provided) to disk and set COINBASE_PEM_PATH
# -----------------------
def _ensure_pem_on_disk() -> Optional[str]:
    """
    If COINBASE_PEM_CONTENT or COINBASE_JWT_PEM is set, write it to COINBASE_PEM_PATH (or /tmp/coinbase.pem)
    and return the path. On failure return None.
    """
    pem_content = os.getenv("COINBASE_PEM_CONTENT") or os.getenv("COINBASE_JWT_PEM")
    if not pem_content:
        LOG.debug("No COINBASE_PEM_CONTENT / COINBASE_JWT_PEM provided.")
        return os.getenv("COINBASE_PEM_PATH")  # may be None

    pem_path = os.getenv("COINBASE_PEM_PATH") or "/tmp/coinbase.pem"
    try:
        p = pathlib.Path(pem_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Normalize common mistakes: ensure beginning/ending markers are present, preserve supplied text
        text = pem_content.strip()
        p.write_text(text + ("\n" if not text.endswith("\n") else ""))
        p.chmod(0o600)
        os.environ["COINBASE_PEM_PATH"] = str(p)
        LOG.info("Wrote COINBASE_PEM_CONTENT to %s", p)
        return str(p)
    except Exception as e:
        LOG.exception("Failed to write PEM to %s: %s", pem_path, e)
        return None

# Ensure PEM file is created early
COINBASE_PEM_PATH = _ensure_pem_on_disk()

# -----------------------
# Read environment config used below
# -----------------------
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # expected to be the UUID/key id or API key string
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_JWT_KID = os.getenv("COINBASE_JWT_KID") or os.getenv("COINBASE_API_KID")
ADVANCED = os.getenv("COINBASE_ADVANCED", "True").lower() in ("1", "true", "yes")

LOG.debug("nija_client startup: loading Coinbase auth config")
LOG.debug(" - base=%s", COINBASE_API_BASE)
LOG.debug(" - advanced=%s", ADVANCED)
LOG.debug(" - jwt_set=%s", bool(os.getenv("COINBASE_JWT_PEM") or os.getenv("COINBASE_PEM_CONTENT")))
LOG.debug(" - api_key_set=%s", bool(COINBASE_API_KEY))
LOG.debug(" - api_passphrase_set=%s", bool(os.getenv("COINBASE_API_PASSPHRASE")))
LOG.debug(" - org_id_set=%s", bool(COINBASE_ORG_ID))
LOG.debug(" - private_key_path_set=%s", bool(COINBASE_PEM_PATH))

# -----------------------
# Adapter: attempt to create a usable client from a few libraries
# -----------------------
class CoinbaseAdapter:
    def __init__(self):
        self.client = None
        self.client_name = "none"
        self._attempt_clients()

    def _attempt_clients(self):
        # 1) Try coinbase_advanced (if you vendor it or install it)
        try:
            # coinbase_advanced's API and constructor may vary; attempt a generic import
            from coinbase_advanced.client import Client as AdvancedClient  # type: ignore
            LOG.info("coinbase_advanced found; attempting to initialize")
            try:
                # If your implementation requires (org_id, pem_path...) adapt here
                if COINBASE_PEM_PATH and COINBASE_ORG_ID:
                    # many advanced libs want org+pem to sign; adapt as necessary
                    client = AdvancedClient(org_id=COINBASE_ORG_ID, pem_path=COINBASE_PEM_PATH)
                else:
                    client = AdvancedClient()
                self.client = client
                self.client_name = "coinbase_advanced"
                LOG.info("Initialized coinbase_advanced client")
                return
            except Exception as e:
                LOG.exception("coinbase_advanced import succeeded but initialization failed: %s", e)
        except Exception:
            LOG.debug("coinbase_advanced not available")

        # 2) Try official coinbase wallet client (legacy) - coinbase.wallet.client.Client
        try:
            from coinbase.wallet.client import Client as WalletClient  # type: ignore
            LOG.info("coinbase.wallet.client available; trying to construct")
            # Official Client typically wants api_key and api_secret, or can be used read-only.
            if COINBASE_API_KEY and COINBASE_API_SECRET:
                try:
                    client = WalletClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET)
                    self.client = client
                    self.client_name = "coinbase.wallet.client"
                    LOG.info("Initialized coinbase.wallet.client with API key/secret")
                    return
                except Exception as e:
                    LOG.exception("Failed to initialize coinbase.wallet.client with key/secret: %s", e)
            else:
                LOG.info("coinbase.wallet.client present but COINBASE_API_KEY/SECRET missing.")
        except Exception:
            LOG.debug("coinbase.wallet.client not available")

        # 3) Fall back to None, but expose diagnostics
        LOG.info("no supported Coinbase client library found; adapter client=None")

    def fetch_accounts(self) -> Optional[Any]:
        """
        Try to fetch account list for sanity checks. Return accounts or raise.
        """
        if not self.client:
            raise RuntimeError("no Coinbase client available")

        # Try common method names across client libs
        # coinbase.wallet.client.Client -> get_accounts(), get_account, get_accounts()
        try:
            if hasattr(self.client, "get_accounts"):
                LOG.debug("Calling client.get_accounts()")
                return self.client.get_accounts()
            if hasattr(self.client, "list_accounts"):
                LOG.debug("Calling client.list_accounts()")
                return self.client.list_accounts()
            if hasattr(self.client, "accounts") and hasattr(self.client.accounts, "list"):
                LOG.debug("Calling client.accounts.list()")
                return self.client.accounts.list()
            # generic fallback: try attribute 'get' or 'request' (very defensive)
            if hasattr(self.client, "get"):
                LOG.debug("Calling client.get('/accounts')")
                return self.client.get("/accounts")
        except Exception as e:
            LOG.exception("Error while fetching accounts: %s", e)
            raise

        raise RuntimeError("client present but no supported accounts method found")

# Instantiate adapter on import so logs appear in container startup
_adapter = CoinbaseAdapter()

def fetch_accounts():
    """
    Public helper: try to fetch accounts and return a truthy result or raise.
    Used by startup checks and tests.
    """
    try:
        accounts = _adapter.fetch_accounts()
        LOG.info("✅ Coinbase connection verified. Accounts fetched: %s", getattr(accounts, "__len__", lambda: None)())
        return accounts
    except Exception as e:
        LOG.error("🔹 Coinbase connection failed: %s", e)
        raise

# Optionally export the adapter and client for other modules
adapter = _adapter
client = _adapter.client
client_name = _adapter.client_name

# Example quick-run sanity check (only run if invoked directly)
if __name__ == "__main__":
    LOG.info("Running quick sanity checks for nija_client.py")
    LOG.info("Adapter client_name=%s", client_name)
    try:
        _ = fetch_accounts()
        LOG.info("Sanity check: fetch_accounts succeeded")
    except Exception:
        LOG.exception("Sanity check failed")
