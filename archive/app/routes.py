from flask import jsonify

def register_routes(app):
    @app.route("/")
    def home():
        return jsonify({"status": "NIJA Trading Bot Online!"})

    @app.route("/health")
    def health():
        return jsonify({"status": "healthy"})
