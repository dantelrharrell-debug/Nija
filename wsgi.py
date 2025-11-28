# wsgi.py
"""
Safe WSGI entrypoint for Gunicorn.
- Always exposes a valid `app` immediately.
- Optionally tries to import `app` module non-fatally.
- If the optional module provides register_to_app(app), it will be invoked.
"""
import logging
import importlib

from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOG = logging.getLogger("nija.wsgi")

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def _index():
        return "Nija Bot Running (wsgi root)!"

    @app.route("/health")
    def health():
        return {"status": "ok"}

    # Optional safer import of richer app module (non-fatal)
    try:
        try:
            mod = importlib.import_module("app")  # your app.py
        except BaseException as be:
            LOG.warning("Optional importlib.import_module('app') raised BaseException; skipping optional import. %s", be)
            mod = None

        if mod:
            # Preferred: app.py can expose a function to register routes safely
            if hasattr(mod, "register_to_app") and callable(getattr(mod, "register_to_app")):
                try:
                    mod.register_to_app(app)
                    LOG.info("Registered routes via app.register_to_app")
                except Exception as e:
                    LOG.exception("register_to_app raised an exception (routes not registered): %s", e)

            # Optional: if module exposes a blueprint object called 'bp', register it
            if hasattr(mod, "bp"):
                try:
                    bp = getattr(mod, "bp")
                    app.register_blueprint(bp)
                    LOG.info("Registered blueprint 'bp' from app module")
                except Exception as e:
                    LOG.exception("registering blueprint 'bp' failed: %s", e)
            else:
                LOG.info("Optional app module imported but did not expose register_to_app() or bp.")
    except Exception:
        LOG.exception("Unexpected error during optional app module import. Continuing with base app.")

    return app

# WSGI callable
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
