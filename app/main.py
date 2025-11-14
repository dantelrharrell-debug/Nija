import app.debug_pem_analyzer

# main.py — guaranteed visible process for Railway
import time, os, sys
from datetime import datetime

def log(msg):
    ts = datetime.utcnow().isoformat() + "Z"
    line = f"{ts} | {msg}"
    print(line, flush=True)

log("MAIN: debug starter beginning")
log(f"MAIN: cwd={os.getcwd()} pid={os.getpid()}")

# list some directories so we can see what's inside the container
for p in [".", "/app", "/tmp", "/workspace", "/home"]:
    try:
        items = os.listdir(p)
        log(f"LS {p}: {items[:10]}")
    except Exception as e:
        log(f"LS {p} failed: {e}")

# write indicator file to /tmp
try:
    with open("/tmp/nija_started.ok", "a") as f:
        f.write(datetime.utcnow().isoformat() + " started\n")
    log("WROTE /tmp/nija_started.ok")
except Exception as e:
    log(f"WRITE FAILED: {e}")

# heartbeat so Railway logs show activity quickly
log("Entering HEARTBEAT loop (every 5s). You should see output immediately.")
while True:
    log("HEARTBEAT - container alive")
    time.sleep(5)
