# main.py — aggressive Railway debug (replace current file)
import time, sys, os, traceback
from datetime import datetime

def write_tmp(msg):
    try:
        with open("/tmp/nija_debug.log", "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass

def log(msg, level="INFO"):
    ts = datetime.utcnow().isoformat() + "Z"
    out = f"{ts} [{level}] {msg}"
    print(out, flush=True)
    write_tmp(out)

log("== DEBUG STARTUP ==")

# Print basic process info immediately
log(f"PID={os.getpid()} PWD={os.getcwd()} PYTHONPATH={sys.path[0]}")

# Show existence of files
for p in ["/app", "/workspace", "/home", "/tmp"]:
    try:
        log(f"LS {p}: " + ", ".join(os.listdir(p)[:10]))
    except Exception as e:
        log(f"LS {p} failed: {e}", "ERROR")

# Env snapshot (masked)
keys = ["COINBASE_API_KEY_ID", "COINBASE_PEM", "COINBASE_ORG_ID"]
for k in keys:
    v = os.getenv(k)
    if v:
        log(f"{k}=<SET length={len(v)}>")
    else:
        log(f"{k}=<MISSING>")

# Try importing app package modules (catch full tracebacks)
try:
    import importlib
    importlib.invalidate_caches()
    try:
        from app.start_bot_main import start_bot_main
        log("Imported app.start_bot_main OK")
    except Exception as e:
        log(f"Import start_bot_main failed: {e}", "ERROR")
        log(traceback.format_exc(), "ERROR")

    try:
        from app.nija_client import CoinbaseClient
        log("Imported app.nija_client CoinbaseClient OK")
    except Exception as e:
        log(f"Import nija_client failed: {e}", "ERROR")
        log(traceback.format_exc(), "ERROR")
except Exception as e:
    log(f"Import checks failed: {e}", "ERROR")
    log(traceback.format_exc(), "ERROR")

# Touch a file to indicate the process reached this point
try:
    open("/tmp/nija_started.ok", "w").write(datetime.utcnow().isoformat() + "\n")
    log("Wrote /tmp/nija_started.ok")
except Exception as e:
    log(f"Failed writing /tmp file: {e}", "ERROR")

log("Entering heartbeat (every 5s). You should see these logs quickly.")
while True:
    log("HEARTBEAT")
    time.sleep(5)
