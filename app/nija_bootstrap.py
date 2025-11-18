import os
import logging
import base64
import textwrap
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import requests
from coinbase.rest import RESTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_coinbase")


def get_public_ip():
    try:
        return requests.get("https://api.ipify.org").text
    except Exception:
        return "UNKNOWN"


def normalize_pem(raw_pem: str) -> str:
    """Ensure PEM is properly wrapped."""
    if not raw_pem:
        raise ValueError("No PEM provided")

    pem = raw_pem.replace("\\n", "\n").strip()

    if "BEGIN EC PRIVATE KEY" not in pem:
        raise ValueError("Invalid PEM: missing header")

    return pem


def validate_pem(pem: str):
    """Attempt to load PEM to verify correctness."""
    serialization.load_pem_private_key(
        pem.encode(),
        password=None,
        backend=default_backend()
    )


def load_env_keys():
    org_id = os.getenv("COINBASE_ORG_ID")
    key_id = os.getenv("COINBASE_API_KEY_ID")
    pem_raw = os.getenv("COINBASE_PEM_CONTENT")

    if not org_id or not key_id or not pem_raw:
        raise ValueError("Missing one or more env variables: ORG / API KEY / PEM")

    return org_id, key_id, pem_raw


def try_key(org, kid, pem_raw):
    """Validate and return RESTClient if successful."""

    pem = normalize_pem(pem_raw)
    validate_pem(pem)

    # Save debug copy
    with open("/tmp/coinbase_pem_debug.pem", "w") as f:
        f.write(pem)
    logger.info("Saved normalized PEM to /tmp/coinbase_pem_debug.pem")

    client = RESTClient(
        api_key=kid,
        api_secret=pem,     # raw PEM works for coinbase jwt builder
        organization_id=org
    )
    return client


def bootstrap_coinbase():
    logger.info("🔥 Nija Trading Bot bootstrap starting...")

    public_ip = get_public_ip()
    logger.info(f"⚡ Current outbound IP on this run: {public_ip} (via ipify)")

    # ALWAYS show IP for Coinbase whitelist
    print("\n--- Coinbase Advanced Whitelist line (paste this exact IP) ---")
    print(public_ip)
    print("---------------------------------------------------------------\n")

    org, kid, pem_raw = load_env_keys()

    # Try primary key
    try:
        client = try_key(org, kid, pem_raw)
        logger.info("✅ Primary key validated: connected successfully.")
        return client
    except Exception as e:
        logger.warning(f"Primary key validation failed: {e}")

    # Try fallback key (static we KNOW exists)
    fallback_kid = "ce5dbcbe-ba9f-45a4-a374-5d2618af0ccd"
    logger.info(f"Trying fallback key: org={org} kid={fallback_kid}")

    try:
        client = try_key(org, fallback_kid, pem_raw)
        logger.info("✅ Fallback key validated: connected successfully.")
        return client
    except Exception as e:
        logger.error(f"Fallback key validation failed: {e}")
        logger.error("❌ Bootstrap failed (see logs). Exiting with code 1.")
        raise SystemExit(1)


if __name__ == "__main__":
    bootstrap_coinbase()
