import logging
from flask import Flask
import os

def create_app():
    # Initialize Flask app
    app = Flask(__name__)

    # Example main route
    @app.route("/")
    def index():
        return "Nija Bot Running!"

    # Optional modules (replace with your real optional module names if any)
    optional_modules = [
        "nija_client.optional_app_module1",
        "nija_client.optional_app_module2"
    ]

    for module_name in optional_modules:
        try:
            mod = __import__(module_name, fromlist=["register_to_app", "bp"])
            if hasattr(mod, "register_to_app"):
                mod.register_to_app(app)
                logging.info(f"Optional module {module_name} registered via register_to_app()")
            elif hasattr(mod, "bp"):
                app.register_blueprint(mod.bp)
                logging.info(f"Optional module {module_name} registered via blueprint")
            else:
                logging.info(f"Optional module {module_name} imported but no register_to_app() or bp found. Ignored.")
        except ModuleNotFoundError:
            logging.info(f"Optional module {module_name} not found. Skipping.")

    return app

# Create the app for Gunicorn
app = create_app()

# Optional: only run if this file is executed directly (not necessary for Gunicorn)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
