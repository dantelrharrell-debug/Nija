# start_nija_live_advanced.py
# Debug entry — prints root listing so we confirm the deployed files.
import os, time
print("ENTRYPOINT: start_nija_live_advanced.py running")
print("CWD:", os.getcwd())
print("ROOT FILES:")
for p in sorted(os.listdir(".")):
    print(" -", p)
print("ENV keys (sample):", sorted(k for k in os.environ.keys() if k.startswith("COINBASE") or k.startswith("RAILWAY")))
time.sleep(1)
print("DONE")
