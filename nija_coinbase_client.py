# Replace existing _make_signed_headers + get_usd_balance with this block

def _make_signed_headers(method: str, request_path: str, body: str = "") -> dict:
    """
    Create Coinbase API signed headers.
    Tries two secret formats:
      1) ascii secret (common)
      2) base64-decoded secret (some systems store secret encoded)
    Also logs safe fingerprints for debugging.
    """
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    api_passphrase = os.getenv("COINBASE_PASSPHRASE", "").strip() or ""

    # safe fingerprints only
    api_key_fp = (api_key[:6] + "..." + api_key[-6:]) if api_key else "<missing>"
    api_secret_fp = (api_secret[:6] + "..." + api_secret[-6:]) if api_secret else "<missing>"

    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + request_path + (body or "")

    # Try ascii secret first
    secret_bytes = None
    try:
        secret_bytes = api_secret.encode("utf-8")
    except Exception:
        secret_bytes = None

    # If ascii attempt fails or signature rejected, later fallback to base64 decode
    def _compute_sig(secret_bytes_local):
        sig = hmac.new(secret_bytes_local, message.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(sig).decode()

    # try ascii secret
    try:
        signature_b64 = _compute_sig(secret_bytes)
        headers = {
            "CB-VERSION": "2025-10-01",
            "CB-ACCESS-KEY": api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": api_passphrase,
            "Content-Type": "application/json",
        }
        if DEBUG:
            logger.debug("[NIJA-DEBUG] Using ascii secret for signature. key_fp=%s secret_fp=%s ts=%s",
                         api_key_fp, api_secret_fp, timestamp)
        return headers, "ascii"
    except Exception:
        # fallback: try base64 decode of secret into raw bytes
        try:
            secret_bytes_b64 = base64.b64decode(api_secret + ("=" * (-len(api_secret) % 4)))
            signature_b64 = _compute_sig(secret_bytes_b64)
            headers = {
                "CB-VERSION": "2025-10-01",
                "CB-ACCESS-KEY": api_key,
                "CB-ACCESS-SIGN": signature_b64,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": api_passphrase,
                "Content-Type": "application/json",
            }
            if DEBUG:
                logger.debug("[NIJA-DEBUG] Using base64-decoded secret for signature. key_fp=%s secret_fp=%s ts=%s",
                             api_key_fp, api_secret_fp, timestamp)
            return headers, "base64"
        except Exception as e:
            logger.error("[NIJA-CLIENT] Failed to prepare secret bytes for HMAC: %s", e)
            raise

def get_usd_balance() -> Decimal:
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        logger.error("[NIJA-CLIENT] Missing COINBASE_API_KEY or COINBASE_API_SECRET in environment.")
        return Decimal(0)

    try:
        request_path = "/v2/accounts"
        headers, secret_mode = _make_signed_headers("GET", request_path, "")
        logger.info("[NIJA-CLIENT] Fetching USD balance via Coinbase REST API (signed, secret_mode=%s)...", secret_mode)

        resp = requests.get("https://api.coinbase.com" + request_path, headers=headers, timeout=10)
        # If 401 or other, log the body to help debugging (masked)
        if resp.status_code >= 400:
            body_preview = resp.text[:1000] if resp.text else "<empty>"
            logger.error("[NIJA-CLIENT] HTTP %s from Coinbase. Body preview: %s", resp.status_code, body_preview)
        resp.raise_for_status()

        data = resp.json()
        accounts = data.get("data", [])
        if DEBUG:
            logger.debug("[NIJA-CLIENT] Full accounts payload: %s", accounts)

        for acct in accounts:
            currency = str(acct.get("currency", "")).upper()
            if currency == "USD":
                balance_str = acct.get("balance", {}).get("amount", "0")
                balance = Decimal(str(balance_str).strip())
                logger.info("[NIJA-CLIENT] USD Balance Detected: $%s", balance)
                return balance

        logger.warning("[NIJA-CLIENT] No USD account found — returning 0.")
        return Decimal(0)

    except requests.exceptions.HTTPError as e:
        resp = getattr(e, "response", None)
        body = None
        try:
            body = resp.text if resp is not None else None
        except Exception:
            body = "<unreadable body>"
        logger.error("[NIJA-CLIENT] Network error fetching USD balance: %s %s", e, body)
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-CLIENT] Unexpected error fetching USD balance: %s", e)
        return Decimal(0)
