import logging
from nija_client import CoinbaseClient, calculate_position_size

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_debug")

def main():
    try:
        log.info("✅ Starting Nija preflight check...")

        client = CoinbaseClient()

        # First, try to validate JWT
        if client.passphrase is None:
            log.info("ℹ️ Using Advanced JWT key. Validating...")
            jwt_valid = client.validate_jwt()
            if not jwt_valid:
                log.warning("⚠️ JWT failed. Trying classic API key if available...")
                if client.passphrase is None:
                    raise RuntimeError("❌ No classic passphrase available for fallback. Cannot continue.")
        else:
            log.info("ℹ️ Using standard API key + passphrase.")

        # Fetch USD spot balance
        try:
            usd_balance = client.get_usd_spot_balance()
            log.info(f"✅ USD Spot Balance: ${usd_balance:.2f}")
        except Exception as e:
            log.error(f"❌ Failed to fetch USD Spot balance: {e}")

        # Example usage of position sizing
        try:
            position_size = calculate_position_size(usd_balance, risk_factor=2.0)
            log.info(f"ℹ️ Calculated trade position size: ${position_size:.2f}")
        except Exception as e:
            log.error(f"❌ Failed to calculate position size: {e}")

        log.info("✅ Nija preflight check complete.")

    except Exception as e:
        log.error(f"❌ Error in Nija debug: {e}")


if __name__ == "__main__":
    main()
