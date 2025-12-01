# web/wsgi.py
from web import create_app  # import your app factory

# Create a top-level 'app' variable that Gunicorn can find
app = create_app()
