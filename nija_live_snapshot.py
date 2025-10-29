# --- BEGIN STARTUP DIAGNOSTIC (must be at VERY TOP of the file) ---
import sys, importlib, os, traceback
print("\n=== NIJA STARTUP DIAGNOSTIC ===\n", flush=True)

# 1) Which python and sys.path
try:
    print("Python executable:", sys.executable, flush=True)
    print("Python version:", sys.version.replace("\n", " "), flush=True)
    print("sys.path (first 10):", sys.path[:10], flush=True)
except Exception:
    traceback.print_exc()

# 2) show pip / importlib metadata (best-effort)
try:
    import importlib.metadata as md
    for name in ("coinbase-advanced-py", "coinbase_advanced_py"):
        try:
            meta = md.metadata(name)
            print(f"Found metadata for {name}", flush=True)
        except Exception:
            pass
except Exception:
    pass

# 3) Try to import top-level package and inspect
try:
    m = importlib.import_module("coinbase_advanced_py")
    print("Imported module:", m, flush=True)
    print("module __file__:", getattr(m, "__file__", None), flush=True)
    print("module __path__:", getattr(m, "__path__", None), flush=True)
    names = [n for n in dir(m) if 'coin' in n.lower() or 'client' in n.lower() or 'coinbase' in n.lower()]
    print("Filtered dir():", names[:60], flush=True)
    print("Has top-level 'CoinbaseClient'?", hasattr(m, "CoinbaseClient"), flush=True)
except Exception as e:
    print("Import error while importing coinbase_advanced_py:", repr(e), flush=True)

# 4) Try submodule import that worked locally
try:
    m2 = importlib.import_module("coinbase_advanced_py.client")
    print("Imported coinbase_advanced_py.client:", m2, flush=True)
    print("client module __file__:", getattr(m2, "__file__", None), flush=True)
    print("Has CoinbaseClient in submodule?", hasattr(m2, "CoinbaseClient"), flush=True)
except Exception as e:
    print("Import error while importing coinbase_advanced_py.client:", repr(e), flush=True)

# 5) List local files that could shadow the package
for check in ('.', './src', './app'):
    try:
        if os.path.exists(check):
            for n in os.listdir(check):
                if n.startswith("coinbase") or n.startswith("coinbase_advanced_py"):
                    print("Possible shadowing file/folder:", os.path.join(check, n), flush=True)
    except Exception:
        pass

# 6) Masked env var check (shows presence but not full value)
def masked(v):
    if v is None: return None
    s = str(v)
    if len(s) <= 6: return "*****"
    return s[:3] + "..." + s[-3:]

print("Environment (masked): COINBASE_API_KEY=", masked(os.getenv("COINBASE_API_KEY")),
      " COINBASE_API_SECRET=", masked(os.getenv("COINBASE_API_SECRET")),
      " COINBASE_PASSPHRASE=", masked(os.getenv("COINBASE_PASSPHRASE")),
      " SANDBOX=", os.getenv("SANDBOX"), flush=True)

print("\n=== END STARTUP DIAGNOSTIC ===\n", flush=True)
# --- END STARTUP DIAGNOSTIC ---

# Now safe to import the rest of the app
import time
import logging
from flask import Flask, jsonify
from threading import Thread

# Attempt to import your client module and show full error if it fails
try:
    from nija_client import client, get_accounts, place_order
    print("Imported nija_client successfully.", flush=True)
except Exception as e:
    print("Failed to import nija_client:", repr(e), flush=True)
    traceback.print_exc()

# ===== Logging =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== Flask App for Health Check =====
app = Flask(__name__)
running = False  # Tracks trading loop

@app.route("/health", methods=["GET"])
def health_check():
    try:
        accounts = get_accounts()
        coinbase_status = "connected" if accounts else "no accounts"
    except Exception as e:
        coinbase_status = f"error: {type(e).__name__}"
    return jsonify({
        "status": "alive",
        "trading": "running" if running else "stopped",
        "coinbase": coinbase_status
    })

# ===== Trading Loop =====
def trading_loop():
    global running
    running = True
    logger.info("Trading loop started")
    try:
        while True:
            try:
                accounts = get_accounts()
            except Exception as e:
                logger.error(f"get_accounts() raised: {e}")
                accounts = []

            if not accounts:
                logger.warning("No accounts available, skipping trade cycle")
                time.sleep(10)
                continue

            # Example: trade BTC-USD with 0.001 BTC per cycle (sandbox safe)
            symbol = "BTC-USD"
            side = "buy"
            size = 0.001

            logger.info(f"Placing order: {side} {size} {symbol}")
            try:
                order = place_order(symbol=symbol, side=side, size=size)
            except Exception as e:
                logger.error(f"place_order() raised: {e}")
                order = None

            if order:
                logger.info(f"Order executed: {order}")
            else:
                logger.error("Order failed")

            # Wait 30 seconds before next trade cycle
            time.sleep(30)
    except Exception as e:
        logger.error(f"Trading loop error: {e}")
    finally:
        running = False
        logger.info("Trading loop stopped")

# ===== Start Trading Thread =====
def start_trading():
    thread = Thread(target=trading_loop, daemon=True)
    thread.start()

# ===== Main Entrypoint =====
if __name__ == "__main__":
    logger.info("Starting Nija bot main...")
    start_trading()
    # Start Flask server for Render
    # Render expects to bind to $PORT, but your logs show you use 10000 — keep as you had
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
