from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)
    # Load config from env or default here, e.g. app.config.from_envvar(...)
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "service": "NIJA Bot"})

    # put your real blueprint / app code import here, e.g. from .routes import register_routes
    return app

# WSGI object expected by many containers
app = create_app()
