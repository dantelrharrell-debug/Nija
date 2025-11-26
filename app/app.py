from flask import Flask
from nija_client import test_coinbase_connection

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Trading Bot Running!"

@app.before_first_request
def startup_checks():
    test_coinbase_connection()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
