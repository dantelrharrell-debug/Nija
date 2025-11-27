# web/wsgi.py
# This file exposes the Flask `app` to Gunicorn as `web.wsgi:app`.

from app import app  # app is created at module level in app.py

# Optionally, set a simple logging bridge so Gunicorn logs appear in the Flask logger
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__('os').environ.get("PORT", 8080)))
