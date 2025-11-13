# main.py  -- debugging helper (Railway friendly)
import os, sys, time, traceback
from datetime import datetime

# ensure unbuffered printing (python -u used in Docker helps too)
def log(msg, level="INFO"):
    ts = datetime.utcnow().isoformat() + "Z"
    line = f"{ts} [{level}] {msg}"
    print(line, flush=True)

# quick environment check (masked)
def env_snapshot():
    keys = ["COINBASE_API_KEY_ID", "COINBASE_PEM", "COINBASE_ORG_ID"]
    out = {}
    for k in keys:
        v = os.getenv(k)
        if v:
            # mask value length only (do NOT print secret)
            out[k] = f"<SET length={len(v)}>"
        else:
            out[k] = "<MISSING>"
    return out

def write_boot_file(msg):
    try:
        with open("/tmp/nija_boot.log", "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass

if __name__ == "__main__":
    try:
        log("=== Nija debug startup ===")
        write_boot_file(f"boot: {datetime.utcnow().isoformat()}")

        # process info
        log(f"PID={os.getpid()} PYTHONPATH={sys.path[0]}")
        snap = env_snapshot()
        for k,v in snap.items():
            log(f"ENV {k} = {v}")

        # quick import test to see import-time errors
        try:
            import importlib
            importlib.invalidate_caches()
            # attempt to import your startup module if present
            try:
                from app.start_bot_main import start_bot_main
                log("Imported app.start_bot_main.start_bot_main OK")
            except Exception as e:
                log(f"Could not import start_bot_main: {e}", level="ERROR")
                log(traceback.format_exc(), level="ERROR")
            # attempt CoinbaseClient import
            try:
                from app.nija_client import CoinbaseClient
                log("Imported app.nija_client.CoinbaseClient OK")
            except Exception as e:
                log(f"Could not import nija_client: {e}", level="ERROR")
                log(traceback.format_exc(), level="ERROR")
        except Exception as e:
            log(f"Import checks failed: {e}", level="ERROR")
            log(traceback.format_exc(), level="ERROR")

        log("Entering heartbeat loop (5s interval). Watch logs now.")
        write_boot_file(f"heartbeat_start: {datetime.utcnow().isoformat()}")

        # heartbeat - short interval so you see output quickly
        while True:
            log("HEARTBEAT - container alive")
            write_boot_file(f"heartbeat: {datetime.utcnow().isoformat()}")
            time.sleep(5)

    except Exception as e:
        log(f"Fatal error in main: {e}", level="ERROR")
        log(traceback.format_exc(), level="ERROR")
        # keep alive so logs are visible for debugging
        while True:
            time.sleep(60)
