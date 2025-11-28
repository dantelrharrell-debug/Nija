# app/nija_client/__init__.py
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "service": "Nija Bot Running!"})
