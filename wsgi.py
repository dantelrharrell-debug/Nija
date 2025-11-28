from flask import Flask
from nija_client.check_funded import check_funded_accounts  # ✅ works now

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
