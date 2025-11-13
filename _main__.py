# main.py — Railway-friendly robust startup + heartbeat
import time
import sys
import inspect
from loguru import logger

# Ensure immediate stdout logs for Railway
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True, backtrace=True, diagnose=True)

def safe_log(msg, level="INFO"):
    if level == "ERROR":
        logger.error(msg)
    elif level == "WARNING":
        logger.warning(msg)
    else:
        logger.info(msg)
    try:
        sys.stdout.flush()
    except Exception:
        pass

safe_log("🔹 Nija bot starting... (robust debug main.py)")

# Try to import the startup function and the CoinbaseClient if available
start_func = None
client_cls = None

# Import attempts with helpful logging
try:
    # Prefer explicit name if present
    from app.start_bot_main import start_bot_main as start_func_candidate
    start_func = start_func_candidate
    safe_log("Imported app.start_bot_main.start_bot_main OK")
except Exception as e:
    safe_log(f"Could not import start_bot_main directly: {e}", "WARNING")

try:
    # Fallback: try module import and look for common entry names
    import importlib
    mod = importlib.import_module("app.start_bot_main")
    safe_log("Imported module app.start_bot_main OK")
    if not start_func:
        # look for common names
        for name in ("start_bot_main", "main", "run", "start"):
            if hasattr(mod, name):
                start_func = getattr(mod, name)
                safe_log(f"Using app.start_bot_main.{name} as startup function")
                break
except Exception as e:
    safe_log(f"Could not import module app.start_bot_main: {e}", "WARNING")

# Try to import CoinbaseClient class if available (so we can pass it if needed)
try:
    from app.nija_client import CoinbaseClient
    client_cls = CoinbaseClient
    safe_log("Imported app.nija_client.CoinbaseClient OK")
except Exception as e:
    safe_log(f"Could not import app.nija_client.CoinbaseClient: {e}", "WARNING")

# Attempt to call the startup function in a flexible way
if start_func:
    try:
        sig = inspect.signature(start_func)
        params = sig.parameters
        # If it takes no parameters -> call directly
        if len(params) == 0:
            safe_log("Calling startup function with no arguments...")
            start_func()
            safe_log("Startup function returned successfully.")
        else:
            # If CoinbaseClient available, try to instantiate and pass it
            if client_cls:
                try:
                    safe_log("Instantiating CoinbaseClient to pass into startup function...")
                    client = client_cls()
                    # try call with client
                    start_func(client)
                    safe_log("Startup function called with CoinbaseClient successfully.")
                except TypeError:
                    # fallback: try passing nothing
                    safe_log("Startup function refused CoinbaseClient param; trying without args...", "WARNING")
                    start_func()
                    safe_log("Startup function returned successfully (no args).")
                except Exception as e:
                    safe_log(f"Error instantiating or calling startup with CoinbaseClient: {e}", "ERROR")
            else:
                # no client available, try calling with no args
                safe_log("Startup function expects args but CoinbaseClient not available — trying without args...", "WARNING")
                start_func()
                safe_log("Startup function returned successfully (no args).")
    except Exception as e:
        safe_log(f"Exception while calling startup function: {e}", "ERROR")
        try:
            import traceback
            safe_log(traceback.format_exc(), "ERROR")
        except Exception:
            pass
else:
    safe_log("No startup function found to call (app.start_bot_main missing).", "WARNING")

# Now keep the container alive and produce regular heartbeat logs so Railway shows output
safe_log("Entering heartbeat loop (every 30s). Check Railway logs for activity.")
while True:
    safe_log("💓 HEARTBEAT - container alive")
    time.sleep(30)
