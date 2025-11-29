# web/wsgi.py
from app import app as flask_app

# Gunicorn expects a WSGI callable called "application" or uses the module:callable string.
application = flask_app
