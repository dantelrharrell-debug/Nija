# app.py
import logging
from flask import Blueprint, jsonify, Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Blueprint containing your main routes (preferred)
bp = Blueprint("nija", __name__)

@bp.route("/nija")
def nija_root():
    return "Nija Bot Running (nija blueprint)!"

@bp.route("/debug/coinbase")
def debug_coinbase():
    """
    Quick diagnostic: reports whether coinbase-advanced can be imported and its version.
    """
    try:
        import importlib, pkg_resources
        mod = importlib.import_module("coinbase_advanced")
        # try to look up distribution if installed as coinbase-advanced-py
        try:
            dist = pkg_resources.get_distribution("coinbase-advanced-py")
            version = dist.version
        except Exception:
            version = getattr(mod, "__version__", "unknown")
        return jsonify({"coinbase_import": True, "version": version})
    except Exception as e:
        return jsonify({"coinbase_import": False, "error": str(e)})

def register_to_app(app: Flask):
    """
    Called by wsgi.create_app(app) to attach blueprint(s) safely.
    """
    if not isinstance(app, Flask):
        raise TypeError("register_to_app expects a Flask instance")
    app.register_blueprint(bp)
    logger.info("Blueprint 'nija' registered via register_to_app")

# ALSO expose a module-level Flask app object (so wsgi.create_app can see mod.app)
# This is intentionally minimal — we do NOT auto-register bp here to avoid double-registration.
app = None
try:
    # create a convenience local app if someone runs this file directly
    _local = Flask(__name__)
    _local.register_blueprint(bp)
    app = _local
    # Keep running-only helper folded behind __main__
except Exception:
    app = None

if __name__ == "__main__":
    # If run directly, create a standalone app and run it.
    server = Flask(__name__)
    register_to_app(server)
    server.run(host="0.0.0.0", port=5000)
