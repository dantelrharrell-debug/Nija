

import requests

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOGLEVEL", "INFO"))

# Simple console handler if none configured upstream
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s:%(lineno)d - %(message)s"))
    logger.addHandler(ch)


class CoinbaseClient:
    """
    Initialize like:
        client = CoinbaseClient()
    Then:
        accounts = client.list_accounts()
        # or backward compatible:
        accounts = client.get_accounts()
        accounts = client.accounts()
    """

    DEFAULT_BASE = "https://api.coinbase.com"            # Coinbase (merchant) API default
    DEFAULT_EXCHANGE_BASE = "https://api.exchange.coinbase.com"  # Coinbase Pro / Exchange base (if needed)

    def __init__(self):
        # Mode flag: "rest" (API_KEY/API_SECRET) or "advanced" (JWT/PEM)
        self.api_type = os.getenv("COINBASE_API_TYPE", "rest").lower()
        self.base_url = os.getenv("COINBASE_API_BASE", self.DEFAULT_BASE)

        # REST credentials
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # sometimes used by exchange endpoints

        # Advanced/JWT credentials
        # Accept either COINBASE_PEM (raw PEM content), COINBASE_PEM_B64 (base64 encoded PEM), or COINBASE_PEM_PATH (existing file)
        self.pem_content = os.getenv("COINBASE_PEM")
        self.pem_b64 = os.getenv("COINBASE_PEM_B64")
        self.pem_path = os.getenv("COINBASE_PEM_PATH")

        # Other optional config
        self.request_timeout = float(os.getenv("COINBASE_REQUEST_TIMEOUT", "10"))

        # Internal: path to written PEM (if used)
        self._written_pem_path: Optional[str] = None

        logger.info("Initializing CoinbaseClient (api_type=%s, base_url=%s)", self.api_type, self.base_url)

        # Validate presence of credentials depending on mode
        self._validate_and_prepare_credentials()

    def _validate_and_prepare_credentials(self):
        """
        Validate environment variables for the selected mode.
        If using PEM content, write it to a temp file for libraries that require a file path.
        Raises ValueError listing which variables are missing.
        """
        missing = []
        if self.api_type == "advanced":
            # advanced mode expects PEM content or path
            if not any([self.pem_content, self.pem_b64, self.pem_path]):
                missing.append("COINBASE_PEM (or COINBASE_PEM_B64 or COINBASE_PEM_PATH)")
            # Optionally accept API key id/email if needed by your JWT flow; do not mandate here.
        else:
            # rest mode requires API key + secret
            if not self.api_key:
                missing.append("COINBASE_API_KEY")
            if not self.api_secret:
                missing.append("COINBASE_API_SECRET")
            # passphrase is optional for some endpoints; warn if missing but don't fail.
            if not self.api_passphrase:
                logger.debug("COINBASE_API_PASSPHRASE not set (may be optional depending on API).")

        if missing:
            logger.error("Missing Coinbase env vars: %s", ", ".join(missing))
            raise ValueError(f"Missing Coinbase API credentials: {', '.join(missing)}")

        # If PEM content is provided, write it to a secure temp file
        if self.api_type == "advanced":
            if self.pem_path:
                if not os.path.exists(self.pem_path):
                    logger.error("COINBASE_PEM_PATH set but file does not exist: %s", self.pem_path)
                    raise ValueError("COINBASE_PEM_PATH points to a non-existent file.")
                self._written_pem_path = self.pem_path
                logger.info("Using existing PEM file from COINBASE_PEM_PATH")
            else:
                pem_text = None
                if self.pem_content:
                    pem_text = self.pem_content
                elif self.pem_b64:
                    try:
                        pem_text = base64.b64decode(self.pem_b64).decode("utf-8")
                    except Exception as e:
                        logger.exception("Failed to base64-decode COINBASE_PEM_B64: %s", e)
                        raise ValueError("COINBASE_PEM_B64 is not valid base64-encoded PEM content.")
                if pem_text:
                    # Normalize escaped newlines if someone stored it as a single-line with \n
                    pem_text = pem_text.replace("\\n", "\n")
                    self._written_pem_path = self._write_pem_to_file(pem_text)
                    logger.info("Wrote PEM content to temporary file: %s", self._written_pem_path)
        else:
            logger.info("REST mode: using API_KEY/SECRET environment variables.")

    def _write_pem_to_file(self, pem_text: str) -> str:
        """
        Write the provided PEM text to a secure temp file and return its path.
        """
        fd, path = tempfile.mkstemp(prefix="coinbase_pem_", suffix=".pem")
        # Close the fd and write with proper permissions
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(pem_text)
        # Set restrictive file permissions
        try:
            os.chmod(path, 0o600)
        except Exception:
            logger.debug("Unable to set strict file permissions on PEM file (non-fatal).")
        return path

    def _get_rest_headers(self, method: str, request_path: str, body: Optional[str] = "") -> Dict[str, str]:
        """
        Build Coinbase REST API headers (signature-based). Works for exchange.coinbase.com style.
        If you use a different client library, adjust accordingly.
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API key/secret are required for REST requests.")

        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + request_path + (body or "")
        secret = self.api_secret.encode("utf-8")
        signature = base64.b64encode(hmac.new(secret, message.encode("utf-8"), hashlib.sha256).digest()).decode()
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            # passphrase is sometimes required for exchange API; include if set.
            "CB-ACCESS-PASSPHRASE": self.api_passphrase or "",
            "Content-Type": "application/json",
        }
        return headers

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, data: Optional[Any] = None):
        """
        Low-level request helper. path should be the full path including leading slash (e.g. "/accounts").
        """
        url = self.base_url.rstrip("/") + path
        body_text = json.dumps(data) if data is not None else ""
        method_up = method.upper()

        # For REST mode, sign the request headers
        if self.api_type != "advanced":
            headers = self._get_rest_headers(method_up, path, body_text)
        else:
            # Advanced/JWT mode: for now we assume a header-based token or library will be used.
            # If you have a JWT creation routine, replace this section to generate Authorization header.
            headers = {"Content-Type": "application/json"}
            logger.debug("Advanced mode: request will use generic headers. Implement JWT header generation if needed.")

        logger.debug("Request %s %s (headers keys: %s)", method_up, url, list(headers.keys()))
        try:
            resp = requests.request(method_up, url, params=params, data=body_text or None, headers=headers, timeout=self.request_timeout)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                return resp.text
        except requests.HTTPError as e:
            logger.error("HTTP error during Coinbase request: %s - %s", resp.status_code if 'resp' in locals() else "N/A", getattr(e, "response", e))
            raise
        except Exception as e:
            logger.exception("Error during Coinbase API request: %s", e)
            raise

    # ---------- Convenience methods ----------
    def list_accounts(self):
        """
        Fetch accounts. This maps to GET /accounts on Coinbase REST API.
        For advanced/JWT flows you may need to change base_url or auth generation.
        Returns parsed JSON response.
        """
        logger.info("Fetching accounts from Coinbase at %s", self.base_url)
        return self._request("GET", "/accounts")

    # Backwards-compatible aliases (some codebases call different method names)
    def get_accounts(self):
        """
        Backwards-compatible alias for list_accounts().
        """
        logger.debug("get_accounts() -> calling list_accounts()")
        return self.list_accounts()

    def accounts(self):
        """
        Extra compatibility alias.
        """
        logger.debug("accounts() -> calling list_accounts()")
        return self.list_accounts()

    def get_account(self, account_id: str):
        """
        Get a specific account by id: GET /accounts/{account_id}
        """
        return self._request("GET", f"/accounts/{account_id}")

    def close(self):
        """
        Cleanup (remove written PEM file if we created one).
        """
        if self._written_pem_path and os.path.exists(self._written_pem_path):
            try:
                os.remove(self._written_pem_path)
                logger.info("Removed temporary PEM file: %s", self._written_pem_path)
            except Exception:
                logger.debug("Failed to remove temporary PEM file (non-fatal).")


# If the file is executed directly, print simple env check results (no secrets).
if __name__ == "__main__":
    try:
        client = CoinbaseClient()
        logger.info("CoinbaseClient initialized successfully.")
        # Note: do not auto-call live API methods in production. Uncomment if you want a live check.
        # accounts = client.list_accounts()
        # logger.info("Accounts fetched: %s", json.dumps(accounts, indent=2)[:1000])
    except Exception as e:
        logger.exception("Failed to initialize CoinbaseClient: %s", e)
        raise
