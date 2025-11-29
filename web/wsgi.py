# web/wsgi.py

from flask import Flask  # or FastAPI, Django, etc. depending on your app

app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Bot is running!"
