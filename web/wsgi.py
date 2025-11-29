# web/wsgi.py
from app.nija_client import app as application  # Gunicorn expects module:application

# Keep this file minimal. Gunicorn will import web.wsgi:application
