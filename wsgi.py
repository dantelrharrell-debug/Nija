# wsgi.py
# Expose application object for gunicorn: "wsgi:app"
from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
