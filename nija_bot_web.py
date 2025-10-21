@app.route("/health", methods=["GET"])
def health_check():
    """
    Returns:
    - status: Flask alive
    - trading: whether the bot thread is running
    - coinbase: whether Coinbase API is reachable
    """
    # Check if trading loop is running
    trading_status = "live" if running else "stopped"

    # Check Coinbase connectivity
    try:
        accounts = client.get_accounts()
        if accounts:
            coinbase_status = "connected"
        else:
            coinbase_status = "no accounts returned"
    except Exception as e:
        coinbase_status = f"error: {e}"

    return jsonify({
        "status": "ok",
        "trading": trading_status,
        "coinbase": coinbase_status
    })
