# --- nija_bootstrap.py ---
import os
import logging
import hashlib
from nija_client import CoinbaseClient  # your existing client module

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def load_and_normalize_pem():
    pem = os.getenv("COINBASE_PEM_CONTENT", "")
    if not pem:
        logging.error("❌ COINBASE_PEM_CONTENT env variable is empty")
        return None

    # Detect escaped \n
    if "\\n" in pem and "\n" not in pem:
        logging.info("Detected escaped-newline PEM (single-line). Converting to multiline.")
        pem_fixed = pem.replace("\\n", "\n")
    else:
        pem_fixed = pem

    # Trim extra whitespace
    pem_fixed = pem_fixed.strip()

    # Save normalized PEM to /tmp for client use
    with open("/tmp/coinbase_pem_debug.pem", "w") as f:
        f.write(pem_fixed)
    logging.info("✅ Saved normalized PEM to /tmp/coinbase_pem_debug.pem")

    # SHA256 fingerprint for debugging (safe)
    fingerprint = hashlib.sha256(pem_fixed.encode("utf-8")).hexdigest()[:12]
    logging.info(f"PEM length={len(pem_fixed)} SHA256-fingerprint={fingerprint}")
    return pem_fixed

def bootstrap_nija_bot():
    pem = load_and_normalize_pem()
    if not pem:
        logging.error("❌ Cannot continue without valid PEM")
        return

    # Load Coinbase environment variables
    org_id = os.getenv("COINBASE_ORG_ID")
    api_key_id = os.getenv("COINBASE_API_KEY_ID")

    if not org_id or not api_key_id:
        logging.error("❌ COINBASE_ORG_ID or COINBASE_API_KEY_ID not set in env")
        return

    logging.info("🔥 Nija Trading Bot bootstrap starting...")
    logging.info(f"⚡ Current outbound IP: (check via ipify or your hosting service)")

    # Attempt primary client connection
    try:
        client = CoinbaseClient(
            org_id=org_id,
            api_key_id=api_key_id,
            pem_content=pem
        )
        logging.info("✅ CoinbaseClient initialized successfully")
    except Exception as e:
        logging.error(f"❌ Primary CoinbaseClient initialization failed: {e}")
        logging.info("Attempting fallback key (if configured)...")
        # You can implement fallback here if you have another key
        return

    # Optional: test a simple API call to confirm connection
    try:
        accounts = client.fetch_accounts()
        logging.info(f"✅ Coinbase connection verified. Accounts fetched: {accounts}")
    except Exception as e:
        logging.error(f"❌ Coinbase API call failed: {e}")
        logging.error("Check PEM, API Key ID, Org ID, IP whitelist, and permissions.")

if __name__ == "__main__":
    bootstrap_nija_bot()
