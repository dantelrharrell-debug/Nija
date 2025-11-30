from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def root():
    return "NIJA BOT ROOT", 200

@app.route("/__nija_probe")
def probe():
    return jsonify({"status": "ok", "bot": "NIJA running"}), 200
