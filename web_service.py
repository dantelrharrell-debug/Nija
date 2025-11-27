from flask import Flask

# Must be top-level for Gunicorn
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"
