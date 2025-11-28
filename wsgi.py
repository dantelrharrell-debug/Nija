from flask import Flask
from nija_client import test_coinbase_connection

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.before_first_request
def startup_checks():
    test_coinbase_connection()
