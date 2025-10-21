# --- Flask app setup ---
app = Flask(__name__)
running = False
lock = threading.Lock()

# --- Health check route ---
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "trading": "live"
    })

# --- Existing routes ---
@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Nija Ultimate AI"}), 200

@app.route("/start")
def start_bot():
    token = request.args.get("token", "")
    if token != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    # ... rest of start_bot code ...

@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != TV_WEBHOOK_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    data = request.json
    print("📡 TradingView alert received:", data)
    return jsonify({"status": "ok", "message": "Webhook received"}), 200
