# /app/web/wsgi.py
from flask import Flask, jsonify
from nija_client import debug_info

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/debug/coinbase")
def debug_coinbase():
    try:
        info = debug_info()
    except Exception as e:
        info = {"error": str(e)}
    return jsonify(info)
