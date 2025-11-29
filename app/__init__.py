# app/__init__.py
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return "NIJA Bot Running!"

@app.route("/health")
def health():
    return jsonify({"status": "ok"})
