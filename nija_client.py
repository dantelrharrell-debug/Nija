# nija_client.py
import os
import base64
from loguru import logger

try:
    # you verified RESTClient imported earlier
    from coinbase.rest import RESTClient
except Exception:
    logger.exception("coinbase.rest import failed - ensure coinbase-advanced-py is in requirements")
    raise

def _load_pem_from_env_or_file():
    """
    Return a PEM string or None.
    Priority:
      1) COINBASE_PEM_CONTENT (raw multi-line PEM)
      2) COINBASE_PEM_B64 (base64-encoded PEM)
      3) COINBASE_PEM_PATH / COINBASE_API_SECRET_PATH (read file)
    """
    pem = os.getenv("COINBASE_PEM_CONTENT")
    if pem:
        return pem

    pem_b64 = os.getenv("COINBASE_PEM_B64")
    if pem_b64:
        try:
            decoded = base64.b64decode(pem_b64).decode("utf-8")
            return decoded
        except Exception:
            logger.exception("Failed to decode COINBASE_PEM_B64")
            return None

    # fallback to file path
    pem_path = os.getenv("COINBASE_PEM_PATH") or os.getenv("COINBASE_API_SECRET_PATH")
    if pem_path and os.path.exists(pem_path):
        try:
            with open(pem_path, "r") as f:
                return f.read()
        except Exception:
            logger.exception("Failed to read PEM file from path")
            return None

    return None

class CoinbaseClient:
    def __init__(self, api_version=None):
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.pem = _load_pem_from_env_or_file()
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE") or None
        # optional API base override (useful for sandbox)
        self.api_base = os.getenv("COINBASE_API_BASE") or None
        self.api_version = api_version or os.getenv("CB_API_VERSION") or os.getenv("CB-VERSION")

        if self.pem and self.org_id:
            logger.info("Using PEM/ORG auth for Coinbase RESTClient (org auth)")
            # Most SDKs accept pem and org_id. If your installed SDK uses different params,
            # update these constructor kwargs.
            kwargs = {"pem": self.pem, "org_id": self.org_id}
            if self.api_version:
                kwargs["version"] = self.api_version
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self.client = RESTClient(**kwargs)
        elif self.api_key and self.api_secret:
            logger.info("Using API key/secret auth for Coinbase RESTClient")
            kwargs = {
                "api_key": self.api_key,
                "api_secret": self.api_secret,
                "api_passphrase": self.api_passphrase
            }
            if self.api_version:
                kwargs["version"] = self.api_version
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self.client = RESTClient(**kwargs)
        else:
            raise ValueError(
                "Missing Coinbase credentials. Set COINBASE_PEM_CONTENT+COINBASE_ORG_ID "
                "or COINBASE_API_KEY+COINBASE_API_SECRET"
            )

    def list_accounts(self):
        """
        Return accounts list-like object.
        Will attempt several likely SDK methods.
        """
        try:
            # Try likely method names
            if hasattr(self.client, "get_accounts"):
                return self.client.get_accounts()
            if hasattr(self.client, "accounts"):
                acct_attr = self.client.accounts
                if callable(acct_attr):
                    return acct_attr()
                # maybe .list()
                if hasattr(acct_attr, "list"):
                    return acct_attr.list()
            # fallback to raw request
            if hasattr(self.client, "request"):
                return self.client.request("GET", "/accounts")
            raise RuntimeError("No known accounts method on RESTClient")
        except Exception:
            logger.exception("list_accounts failed")
            raise
