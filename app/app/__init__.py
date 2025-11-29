from flask import Flask

app = Flask(__name__)

@app.before_first_request
def init_app_first_request():
    print("Flask app started: before_first_request")
