import sys
sys.path.insert(0, "/app")  # ensures /app is on Python path

from app.app import app

try:
    from nija_client.check_funded import check_funded_accounts
except ModuleNotFoundError:
    print("[ERROR] nija_client or check_funded.py missing")
    sys.exit(1)

if not check_funded_accounts():
    print("[ERROR] No funded accounts. Exiting.")
    sys.exit(1)
