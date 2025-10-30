# app.py
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Trading Bot online!"
