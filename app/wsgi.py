from flask import Flask
from nija_client.check_funded import check_funded_accounts
import sys

# Pre-check: funded accounts
if not check_funded_accounts():
    print("[ERROR] No funded accounts. Exiting.")
    sys.exit(1)

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"
