# start_nija_live_advanced.py
# Minimal file to confirm presence and stop the "no such file" loop.
# Replace with real entrypoint later.

import os, time
print("ENTRYPOINT: start_nija_live_advanced.py running")
print("CWD:", os.getcwd())
print("ROOT FILES:")
for p in sorted(os.listdir(".")):
    print(" -", p)
# print env vars helpful for debugging (do NOT include secrets here if logs are public)
print("ENV keys (sample):", sorted(k for k in os.environ.keys() if k.startswith("COINBASE") or k.startswith("RAILWAY") ) )
# short sleep to allow logs to be captured then exit
time.sleep(1)
print("Done")
