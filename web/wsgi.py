# web/wsgi.py
from flask import Flask

# Create the Flask app
app = Flask(__name__)

# Minimal route to test
@app.route("/")
def hello():
    return "NIJA Trading Bot is running!"

# This allows running locally with `python wsgi.py` (optional)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
