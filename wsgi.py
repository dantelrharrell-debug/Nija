# wsgi.py
import sys

try:
    from nija_client.check_funded import check_funded_accounts
except ModuleNotFoundError:
    print("[ERROR] nija_client or check_funded.py missing")
    sys.exit(1)

from app import app  # your Flask app defined in app/__init__.py

if not check_funded_accounts():
    print("[ERROR] No funded accounts. Exiting.")
    sys.exit(1)
