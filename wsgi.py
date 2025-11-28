from flask import Flask
import sys

# Pre-check: funded accounts
try:
    from nija_client.check_funded import check_funded_accounts
except ModuleNotFoundError:
    print("[ERROR] nija_client or check_funded.py missing")
    sys.exit(1)

if not check_funded_accounts():
    print("[ERROR] No funded accounts. Exiting.")
    sys.exit(1)

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"
