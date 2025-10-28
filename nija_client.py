import threading, time

def trading_loop(client):
    while True:
        # Replace this with your trading logic
        try:
            accounts = client.get_accounts()
            # Example: print balances
            for acc in accounts:
                print(f"{acc['currency']}: {acc['balance']['amount']}")
        except Exception as e:
            print(f"[trading-loop] Error: {e}")
        time.sleep(5)

def run_trader(client):
    t = threading.Thread(target=trading_loop, args=(client,))
    t.daemon = True
    t.start()
    print("🔥 Trading loop started 🔥")

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down trading loop…")
