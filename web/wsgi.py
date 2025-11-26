# web/wsgi.py
import logging
import os
import traceback
from flask import Flask, send_file, abort, jsonify

# ----------------------
# App & logging (create app before any routes)
# ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.wsgi")

app = Flask(__name__)

# ----------------------
# Paths
# ----------------------
LOG_DIR = "/app/logs"
DEBUG_FILE = os.path.join(LOG_DIR, "coinbase_module_debug.txt")
MODULES_DEBUG = os.path.join(LOG_DIR, "modules_debug.txt")
os.makedirs(LOG_DIR, exist_ok=True)

# ----------------------
# Safe import of nija_client.test_coinbase_connection
# ----------------------
test_coinbase_connection = None
try:
    # nija_client should expose test_coinbase_connection()
    from nija_client import test_coinbase_connection as _t
    test_coinbase_connection = _t
    logger.info("Imported nija_client.test_coinbase_connection")
except Exception as e:
    test_coinbase_connection = None
    logger.warning("nija_client import failed (Coinbase test will be skipped): %s", e)
    with open(DEBUG_FILE, "w") as f:
        f.write("nija_client import failed at startup:\n")
        traceback.print_exc(file=f)

# ----------------------
# Startup check (safe, non-fatal)
# ----------------------
def run_startup_coinbase_check():
    if test_coinbase_connection is None:
        logger.warning("Coinbase client not available (module not installed).")
        return False

    try:
        ok = bool(test_coinbase_connection())
        if not ok:
            logger.warning("Coinbase connection test failed at startup. App will continue; check /debug/coinbase for details.")
            with open(DEBUG_FILE, "w") as f:
                f.write("Coinbase test returned False at startup.\n")
        else:
            logger.info("Coinbase connection test succeeded at startup.")
        return ok
    except Exception:
        logger.exception("Coinbase test raised an exception at startup; writing debug file.")
        with open(DEBUG_FILE, "w") as f:
            f.write("Coinbase init raised exception:\n")
            traceback.print_exc(file=f)
        return False

# Run once (does NOT exit the app on failure)
startup_coinbase_ok = run_startup_coinbase_check()

# ----------------------
# Routes (app already defined above)
# ----------------------
@app.route("/")
def index():
    return "Nija Trading Bot is running!"

@app.route("/debug/coinbase")
def debug_coinbase():
    if not os.path.exists(DEBUG_FILE):
        return "Debug file not yet created. Coinbase test either succeeded or hasn't run. If failing, check logs.\n", 404
    try:
        return send_file(DEBUG_FILE, mimetype="text/plain", as_attachment=True, download_name="coinbase_module_debug.txt")
    except Exception as e:
        logger.exception("Failed to send coinbase debug file: %s", e)
        abort(500, description=str(e))

@app.route("/debug/modules")
def debug_modules():
    """
    Returns a JSON object listing which import candidates are present and the python path.
    Useful to debug different module names (coinbase_advanced, coinbase_advanced_py, etc).
    """
    candidates = [
        "coinbase_advanced",
        "coinbase_advanced.client",
        "coinbase_advanced_py",
        "coinbase_advanced_py.client",
        "coinbaseadvanced",
    ]
    found = {}
    for name in candidates:
        try:
            __import__(name)
            found[name] = True
        except Exception as e:
            found[name] = False

    info = {
        "found": found,
        "python_path": os.environ.get("PYTHONPATH", ""),
        "sys_path_sample": __import__("sys").path[:10],  # don't dump too long
        "startup_coinbase_ok": bool(startup_coinbase_ok),
    }

    # write to modules debug file for offline inspection
    try:
        with open(MODULES_DEBUG, "w") as f:
            f.write(str(info))
    except Exception:
        logger.exception("Failed to write modules debug file.")

    return jsonify(info)

# ----------------------
# Optionally expose gunicorn-ready callable
# ----------------------
# The WSGI callable 'app' is already defined for gunicorn: web.wsgi:app

# ----------------------
# If you run this file directly (for local dev)
# ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
