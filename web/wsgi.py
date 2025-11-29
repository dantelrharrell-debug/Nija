from flask import Flask

# Create Flask app
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

# This is required by Gunicorn
application = app
