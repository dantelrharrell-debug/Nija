# web/wsgi.py
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Bot is running!"
