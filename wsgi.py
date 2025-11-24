# web/wsgi.py
from flask import Flask
from web.tradingview_webhook import bp  # matches the 'bp' blueprint

app = Flask(__name__)

# Register the TradingView blueprint under /tv
app.register_blueprint(bp, url_prefix='/tv')

# Optional: basic health check route
@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
