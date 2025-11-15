def test_coinbase(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")
    }
    try:
        # Advanced Trade API endpoint
        resp = requests.get("https://api.exchange.coinbase.com/accounts", headers=headers, timeout=12)
        return resp
    except Exception as e:
        logger.exception(f"Coinbase request failed: {e}")
        return None
