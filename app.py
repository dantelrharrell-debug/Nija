# app.py
from flask import Flask
from nija_client import client
from signals import generate_signal

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Trading Bot online!"

# Example route to test generate_signal
@app.route("/signal/<symbol>")
def signal(symbol):
    try:
        sig = generate_signal(symbol, client=client)
        return {"symbol": symbol, "signal": sig}
    except Exception as e:
        return {"error": str(e)}, 500
