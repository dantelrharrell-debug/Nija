# wsgi.py
from app.app import app

# Exposes `app` for gunicorn:  gunicorn wsgi:app
if __name__ == "__main__":
    # Useful for local dev: `python wsgi.py`
    app.run(host="0.0.0.0", port=8080, debug=True)
