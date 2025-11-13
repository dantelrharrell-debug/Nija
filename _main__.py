# main.py — minimal guaranteed visible process for Railway
import time, sys, os
from datetime import datetime

def log(msg):
    ts = datetime.utcnow().isoformat() + "Z"
    line = f"{ts} | {msg}"
    print(line, flush=True)

log("MAIN: starting debug main.py")
log(f"MAIN: cwd={os.getcwd()} pid={os.getpid()}")

# quick filesystem check
for p in [".", "/app", "/workspace", "/tmp"]:
    try:
        items = os.listdir(p)
        log(f"LS {p}: {items[:8]}")
    except Exception as e:
        log(f"LS {p} failed: {e}")

# write a small file to /tmp so you can verify container executed code
try:
    with open("/tmp/nija_started.ok", "a") as f:
        f.write(datetime.utcnow().isoformat() + " started\n")
    log("WROTE /tmp/nija_started.ok")
except Exception as e:
    log(f"WRITE FAILED: {e}")

# heartbeat — prints every 5s so logs appear quickly
while True:
    log("HEARTBEAT - container is alive")
    time.sleep(5)
