# web/wsgi.py
import logging
import os
import traceback
from flask import Flask, send_file, abort, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.wsgi")

app = Flask(__name__)

LOG_DIR = "/app/logs"
DEBUG_FILE = os.path.join(LOG_DIR, "coinbase_module_debug.txt")
MODULES_DEBUG = os.path.join(LOG_DIR, "modules_debug.txt")
os.makedirs(LOG_DIR, exist_ok=True)

# Attempt to import the symbol. We intentionally import the symbol name,
# but we will *verify* it is callable before calling.
test_coinbase_connection = None
try:
    # prefer direct function import if available
    from nija_client import test_coinbase_connection as _t
    test_coinbase_connection = _t
    logger.info("Imported nija_client.test_coinbase_connection")
except Exception as e:
    test_coinbase_connection = None
    logger.warning("nija_client import failed (Coinbase test will be skipped): %s", e)
    with open(DEBUG_FILE, "w") as f:
        f.write("nija_client import failed at startup:\n")
        traceback.print_exc(file=f)

def run_startup_coinbase_check():
    # Clear old debug file
    try:
        if os.path.exists(DEBUG_FILE):
            os.remove(DEBUG_FILE)
    except Exception:
        logger.debug("Couldn't remove old debug file.")

    if test_coinbase_connection is None:
        logger.warning("Coinbase client not available (module not installed).")
        with open(DEBUG_FILE, "w") as f:
            f.write("nija_client import failed or is missing.\n")
        return False

    # IMPORTANT: verify the imported object is callable (function)
    if not callable(test_coinbase_connection):
        ttype = type(test_coinbase_connection)
        logger.error("test_coinbase_connection imported but is NOT callable. type=%s repr=%r", ttype, test_coinbase_connection)
        with open(DEBUG_FILE, "w") as f:
            f.write("test_coinbase_connection imported but not callable.\n")
            f.write(f"type: {ttype}\nrepr:\n{repr(test_coinbase_connection)}\n\nTraceback:\n")
            traceback.print_stack(file=f)
        return False

    try:
        ok = bool(test_coinbase_connection())
        if not ok:
            logger.warning("Coinbase connection test returned False at startup. App will continue; check /debug/coinbase for details.")
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

startup_coinbase_ok = run_startup_coinbase_check()

# Routes
@app.route("/")
def index():
    return "Nija Trading Bot is running!"

@app.route("/debug/coinbase")
def debug_coinbase():
    if not os.path.exists(DEBUG_FILE):
        return "Debug file not yet created. If coinbase test failed, check logs.\n", 404
    try:
        return send_file(DEBUG_FILE, mimetype="text/plain", as_attachment=True, download_name="coinbase_module_debug.txt")
    except Exception as e:
        logger.exception("Failed to send coinbase debug file: %s", e)
        abort(500, description=str(e))

@app.route("/debug/modules")
def debug_modules():
    candidates = [
        "coinbase_advanced",
        "coinbase_advanced.client",
        "coinbase_advanced_py",
        "coinbase_advanced_py.client",
        "coinbaseadvanced",
    ]
    found = {}
    import sys
    for name in candidates:
        try:
            __import__(name)
            found[name] = True
        except Exception as e:
            found[name] = False

    info = {
        "found": found,
        "python_path": os.environ.get("PYTHONPATH", ""),
        "sys_path_sample": sys.path[:10],
        "startup_coinbase_ok": bool(startup_coinbase_ok),
    }

    try:
        with open(MODULES_DEBUG, "w") as f:
            f.write(str(info))
    except Exception:
        logger.exception("Failed to write modules debug file.")

    return jsonify(info)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
