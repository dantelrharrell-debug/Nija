# web/wsgi.py
import os
import logging
import traceback

# ensure logs go to stdout for container logs
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.wsgi")

try:
    # Prefer factory-style create_app if available
    # It should return a Flask app instance.
    # Try several common locations so this file is resilient.
    app = None

    # Try importing a create_app factory from the package
    try:
        from . import create_app as package_create_app  # web.create_app
        logger.debug("Found web.create_app()")
        app = package_create_app()
    except Exception as e:
        logger.debug("web.create_app not found or raised: %s", e)

    # Fallback: try top-level app variable
    if app is None:
        try:
            from . import app as package_app  # web.app
            logger.debug("Found web.app")
            app = package_app
        except Exception as e:
            logger.debug("web.app not found or raised: %s", e)

    # Final fallback: try importing module `web` then attribute `app`
    if app is None:
        try:
            import web
            logger.debug("Imported package `web`, looking for app attribute")
            app = getattr(web, "app", None)
        except Exception as e:
            logger.debug("Import web failed: %s", e)

    if app is None:
        # Try the old-style top-level wsgi app (less common)
        try:
            # try app from parent module `app`
            import app as top_app
            app = getattr(top_app, "app", None)
            if app:
                logger.debug("Found top-level app.app")
        except Exception:
            pass

    if app is None:
        raise RuntimeError(
            "Could not locate a Flask `app` instance. "
            "Make sure web.create_app() or web.app exists and does not raise during import."
        )

except Exception as exc:
    # Print full traceback so container logs show the root cause
    logger.error("Failed to import or create Flask app: %s", exc)
    traceback.print_exc()
    # Re-raise to let Gunicorn display its normal error/stop
    raise

# Expose the Flask app as `app` for Gunicorn
# (Gunicorn will import web.wsgi:app)
