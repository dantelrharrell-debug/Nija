# web/wsgi.py
from web.app import app  # Import your Flask app instance
application = app       # Expose as 'application' for WSGI
