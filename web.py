# web.py — top-level proxy so `gunicorn web:app` works
from web.wsgi import app  # exposes `app` at module level
