# web/wsgi.py
from app.web_app import create_app  # Adjust import to your Flask app
application = create_app()
