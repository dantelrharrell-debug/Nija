# wsgi.py - minimal wrapper that exposes `app` for gunicorn/uvicorn.
# Adjust the import to point to where your app object actually lives.
try:
    # Common location: main.py defines `app = Flask(...)` or `app = FastAPI()`
    from main import app  # preferred if main.py contains the app object
except Exception:
    try:
        # Alternative: web/app.py defines `app`
        from web.app import app
    except Exception:
        # If you use a factory create_app(), try that:
        try:
            from main import create_app
            app = create_app()
        except Exception:
            raise ImportError(
                "wsgi.py failed to import app. Ensure `app` exists in main.py or web/app.py, "
                "or implement create_app() in main.py. See logs for details."
            )
