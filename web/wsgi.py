# web/wsgi.py
# Gunicorn WSGI entrypoint for the NIJA web app.
# Exposes `application` which Gunicorn expects.

# Support two common patterns:
# 1) web.create_app() factory -> use that
# 2) web.app Flask instance -> use that

try:
    # If your package has a factory create_app()
    from web import create_app  # type: ignore
    application = create_app()
except Exception:
    try:
        # Fallback: web package exposes `app` (Flask instance)
        from web import app as application  # type: ignore
    except Exception as exc:
        # Provide a clear startup error for runtime logs
        raise RuntimeError(
            "Failed to load Flask application. Ensure web/__init__.py defines "
            "either create_app() or an `app` Flask instance."
        ) from exc
