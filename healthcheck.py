# health_check.py
import importlib
import sys
import os

print("[INFO] Verifying bot.live_bot_script module and start_trading_loop...")

try:
    mod = importlib.import_module("bot.live_bot_script")
except Exception as e:
    print("[ERROR] Failed to import bot.live_bot_script:", repr(e))
    sys.exit(20)

if not hasattr(mod, "start_trading_loop"):
    print("[ERROR] bot.live_bot_script does not define 'start_trading_loop'.")
    # show available attributes for debugging
    print("Available names in bot.live_bot_script:", [n for n in dir(mod) if not n.startswith("_")])
    sys.exit(21)

print("[OK] start_trading_loop found:", mod.start_trading_loop)
print("[INFO] health_check passed.")
sys.exit(0)
