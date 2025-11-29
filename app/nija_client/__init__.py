# app/nija_client/__init__.py
from flask import Flask

app = Flask(__name__)

# Example route for sanity:
@app.route("/_health")
def _health():
    return "ok", 200
